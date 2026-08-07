#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <fideslib.hpp>
#include "CKKS/AccumulateBroadcast.cuh"

#include "fides_backend.hpp"

namespace {

using Ciphertext = fideslib::Ciphertext<fideslib::DCRTPoly>;
using Clock = std::chrono::steady_clock;
constexpr std::size_t kBatchSize = 8192;
constexpr std::size_t kMaximumValues = 1000000;

double elapsed(const Clock::time_point& started) {
    return std::chrono::duration<double>(Clock::now() - started).count();
}

std::map<std::string, std::string> parse_arguments(int argc, char** argv) {
    std::map<std::string, std::string> arguments;
    for (int index = 1; index < argc; index += 2) {
        if (index + 1 >= argc || std::string(argv[index]).rfind("--", 0) != 0) {
            throw std::invalid_argument("arguments must be --name value pairs");
        }
        arguments.emplace(std::string(argv[index]).substr(2), argv[index + 1]);
    }
    return arguments;
}

const std::string& required(
    const std::map<std::string, std::string>& arguments,
    const std::string& name) {
    const auto found = arguments.find(name);
    if (found == arguments.end() || found->second.empty()) {
        throw std::invalid_argument("missing --" + name);
    }
    return found->second;
}

std::vector<double> parse_values(const std::string& text) {
    std::vector<double> values;
    std::size_t start = 0;
    while (start <= text.size()) {
        const std::size_t end = text.find(',', start);
        const std::string item = text.substr(start, end - start);
        if (item.empty()) {
            throw std::invalid_argument("vectors must contain numbers");
        }
        std::size_t consumed = 0;
        const double value = std::stod(item, &consumed);
        if (consumed != item.size() || !std::isfinite(value)) {
            throw std::invalid_argument("vectors must contain finite numbers");
        }
        values.push_back(value);
        if (end == std::string::npos) {
            break;
        }
        start = end + 1;
    }
    if (values.empty() || values.size() > 4096) {
        throw std::invalid_argument("vector length must be between 1 and 4096");
    }
    return values;
}

std::vector<double> read_binary_values(const std::string& filename) {
    std::ifstream input(filename, std::ios::binary | std::ios::ate);
    if (!input) {
        throw std::invalid_argument("cannot open --input-file");
    }
    const std::streamsize bytes = input.tellg();
    if (bytes <= 0 || bytes % static_cast<std::streamsize>(sizeof(double)) != 0) {
        throw std::invalid_argument("input file must contain binary float64 values");
    }
    const auto count = static_cast<std::size_t>(bytes / sizeof(double));
    if (count > kMaximumValues) {
        throw std::invalid_argument("input file exceeds the 1000000 value limit");
    }
    std::vector<double> values(count);
    input.seekg(0);
    input.read(reinterpret_cast<char*>(values.data()), bytes);
    if (!input || !std::all_of(values.begin(), values.end(), [](double value) {
            return std::isfinite(value);
        })) {
        throw std::invalid_argument("input file contains invalid float64 values");
    }
    return values;
}

void print_simple_result(
    const std::string& operation, const std::vector<double>& values) {
    std::cout << "{\"operation\":\"" << operation << "\",\"values\":[";
    std::cout << std::setprecision(15);
    for (std::size_t index = 0; index < values.size(); ++index) {
        if (index != 0) {
            std::cout << ',';
        }
        std::cout << values[index];
    }
    std::cout << "]}\n";
}

void print_sum_result(
    double value,
    std::size_t value_count,
    std::size_t chunks,
    double context_keygen_seconds,
    double encrypt_seconds,
    double sum_seconds,
    double combine_seconds,
    double decrypt_seconds,
    double total_seconds) {
    std::cout << std::setprecision(15)
              << "{\"operation\":\"sum\",\"values\":[" << value
              << "],\"value_count\":" << value_count
              << ",\"batch_size\":" << kBatchSize
              << ",\"chunks\":" << chunks
              << ",\"timings\":{"
              << "\"context_keygen_seconds\":" << context_keygen_seconds << ','
              << "\"encrypt_seconds\":" << encrypt_seconds << ','
              << "\"sum_seconds\":" << sum_seconds << ','
              << "\"combine_seconds\":" << combine_seconds << ','
              << "\"decrypt_seconds\":" << decrypt_seconds << ','
              << "\"total_seconds\":" << total_seconds << "}}\n";
}

fideslib::CryptoContext<fideslib::DCRTPoly> create_context() {
    fideslib::CCParams<fideslib::CryptoContextCKKSRNS> parameters;
    parameters.SetMultiplicativeDepth(3);
    parameters.SetFirstModSize(60);
    parameters.SetScalingModSize(50);
    parameters.SetScalingTechnique(fideslib::FLEXIBLEAUTO);
    parameters.SetSecurityLevel(fideslib::HEStd_128_classic);
    parameters.SetRingDim(16384);
    parameters.SetBatchSize(static_cast<uint32_t>(kBatchSize));
    parameters.SetDevices({0});
    parameters.SetPlaintextAutoload(false);
    parameters.SetCiphertextAutoload(true);
    auto context = fideslib::GenCryptoContext(parameters);
    context->Enable(fideslib::PKE);
    context->Enable(fideslib::KEYSWITCH);
    context->Enable(fideslib::LEVELEDSHE);
    context->Enable(fideslib::ADVANCEDSHE);
    return context;
}

void run_large_sum(const std::vector<double>& values) {
    const auto total_started = Clock::now();
    const auto setup_started = Clock::now();
    auto context = create_context();
    auto keys = context->KeyGen();
    const auto rotation_indices = FIDESlib::CKKS::GetAccumulateRotationIndices(
        4, 1, static_cast<int>(kBatchSize));
    context->EvalRotateKeyGen(
        keys.secretKey,
        std::vector<int32_t>(rotation_indices.begin(), rotation_indices.end()));
    context->LoadContext(keys.publicKey);
    const double context_keygen_seconds = elapsed(setup_started);

    he_gpu::FidesBackend backend(context);
    Ciphertext encrypted_total;
    double encrypt_seconds = 0.0;
    double sum_seconds = 0.0;
    double combine_seconds = 0.0;
    std::size_t chunks = 0;

    for (std::size_t offset = 0; offset < values.size(); offset += kBatchSize) {
        const std::size_t valid_count =
            std::min(kBatchSize, values.size() - offset);
        std::vector<double> chunk(kBatchSize, 0.0);
        std::copy_n(values.begin() + static_cast<std::ptrdiff_t>(offset),
                    valid_count, chunk.begin());

        const auto encrypt_started = Clock::now();
        auto plaintext = context->MakeCKKSPackedPlaintext(chunk);
        auto encrypted = context->Encrypt(keys.publicKey, plaintext);
        encrypt_seconds += elapsed(encrypt_started);

        const auto sum_started = Clock::now();
        auto encrypted_sum = backend.sum(encrypted, static_cast<int>(kBatchSize));
        sum_seconds += elapsed(sum_started);

        if (!encrypted_total) {
            encrypted_total = encrypted_sum;
        } else {
            const auto combine_started = Clock::now();
            encrypted_total = backend.add(encrypted_total, encrypted_sum);
            combine_seconds += elapsed(combine_started);
        }
        ++chunks;
    }

    const auto decrypt_started = Clock::now();
    fideslib::Plaintext decrypted;
    const auto result = context->Decrypt(keys.secretKey, encrypted_total, &decrypted);
    if (!result.isValid) {
        throw std::runtime_error("FIDESlib decryption failed");
    }
    decrypted->SetLength(1);
    const double value = decrypted->GetRealPackedValue().at(0);
    const double decrypt_seconds = elapsed(decrypt_started);
    print_sum_result(
        value, values.size(), chunks, context_keygen_seconds, encrypt_seconds,
        sum_seconds, combine_seconds, decrypt_seconds, elapsed(total_started));
}

void run_small_operation(
    const std::string& operation,
    std::vector<double> left,
    std::vector<double> right,
    std::size_t input_length) {
    left.resize(kBatchSize, 0.0);
    right.resize(kBatchSize, 0.0);
    auto context = create_context();
    auto keys = context->KeyGen();
    if (operation == "multiply" || operation == "square" ||
        operation == "variance") {
        context->EvalMultKeyGen(keys.secretKey);
    }
    if (operation == "sum" || operation == "mean" ||
        operation == "variance") {
        const auto rotations = FIDESlib::CKKS::GetAccumulateRotationIndices(
            4, 1, static_cast<int>(kBatchSize));
        context->EvalRotateKeyGen(
            keys.secretKey,
            std::vector<int32_t>(rotations.begin(), rotations.end()));
    }
    context->LoadContext(keys.publicKey);
    he_gpu::FidesBackend backend(context);
    auto left_plaintext = context->MakeCKKSPackedPlaintext(left);
    auto left_ciphertext = context->Encrypt(keys.publicKey, left_plaintext);
    Ciphertext result;
    if (operation == "sum") {
        result = backend.sum(left_ciphertext, static_cast<int>(input_length));
    } else if (operation == "mean") {
        result = backend.mean(left_ciphertext, static_cast<int>(input_length));
    } else if (operation == "variance") {
        result = backend.variance(left_ciphertext, static_cast<int>(input_length));
    } else if (operation == "square") {
        result = backend.square(left_ciphertext);
    } else {
        auto right_plaintext = context->MakeCKKSPackedPlaintext(right);
        auto right_ciphertext = context->Encrypt(keys.publicKey, right_plaintext);
        if (operation == "add") result = backend.add(left_ciphertext, right_ciphertext);
        else if (operation == "subtract") result = backend.subtract(left_ciphertext, right_ciphertext);
        else result = backend.multiply(left_ciphertext, right_ciphertext);
    }
    fideslib::Plaintext decrypted;
    const auto decrypted_result = context->Decrypt(keys.secretKey, result, &decrypted);
    if (!decrypted_result.isValid) {
        throw std::runtime_error("FIDESlib decryption failed");
    }
    const std::size_t result_length =
        (operation == "sum" || operation == "mean" || operation == "variance")
        ? 1 : input_length;
    decrypted->SetLength(result_length);
    auto result_values = decrypted->GetRealPackedValue();
    result_values.resize(result_length);
    print_simple_result(operation, result_values);
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto arguments = parse_arguments(argc, argv);
        const auto& operation = required(arguments, "operation");
        if (operation != "add" && operation != "subtract" &&
            operation != "multiply" && operation != "square" &&
            operation != "sum" && operation != "mean" &&
            operation != "variance") {
            throw std::invalid_argument("unsupported operation");
        }
        const auto input_file = arguments.find("input-file");
        if (input_file != arguments.end()) {
            if (operation != "sum") {
                throw std::invalid_argument("--input-file currently supports only sum");
            }
            run_large_sum(read_binary_values(input_file->second));
            return 0;
        }
        auto left = parse_values(required(arguments, "left"));
        const std::size_t input_length = left.size();
        std::vector<double> right;
        if (operation == "add" || operation == "subtract" ||
            operation == "multiply") {
            right = parse_values(required(arguments, "right"));
            if (left.size() != right.size()) {
                throw std::invalid_argument("left and right vectors must have equal length");
            }
        }
        run_small_operation(
            operation, std::move(left), std::move(right), input_length);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "he-gpu-demo: " << error.what() << '\n';
        return 1;
    }
}
