#include <algorithm>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

#include <fideslib.hpp>
#include "CKKS/AccumulateBroadcast.cuh"

#include "fides_backend.hpp"

namespace {

using Ciphertext = fideslib::Ciphertext<fideslib::DCRTPoly>;

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

std::size_t next_power_of_two(std::size_t value) {
    std::size_t result = 1;
    while (result < value) {
        result *= 2;
    }
    return std::max<std::size_t>(result, 8);
}

void print_result(const std::string& operation, const std::vector<double>& values) {
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

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto arguments = parse_arguments(argc, argv);
        const auto& operation = required(arguments, "operation");
        if (operation != "add" && operation != "subtract" &&
            operation != "multiply" && operation != "sum") {
            throw std::invalid_argument("unsupported operation");
        }

        auto left = parse_values(required(arguments, "left"));
        std::vector<double> right;
        if (operation != "sum") {
            right = parse_values(required(arguments, "right"));
            if (left.size() != right.size()) {
                throw std::invalid_argument("left and right vectors must have equal length");
            }
        }

        const std::size_t result_length = operation == "sum" ? 1 : left.size();
        const std::size_t batch_size = next_power_of_two(left.size());
        left.resize(batch_size, 0.0);
        if (operation != "sum") {
            right.resize(batch_size, 0.0);
        }

        fideslib::CCParams<fideslib::CryptoContextCKKSRNS> parameters;
        parameters.SetMultiplicativeDepth(1);
        parameters.SetScalingModSize(50);
        parameters.SetBatchSize(static_cast<uint32_t>(batch_size));
        parameters.SetDevices({0});
        parameters.SetPlaintextAutoload(false);
        parameters.SetCiphertextAutoload(true);

        auto context = fideslib::GenCryptoContext(parameters);
        context->Enable(fideslib::PKE);
        context->Enable(fideslib::KEYSWITCH);
        context->Enable(fideslib::LEVELEDSHE);

        auto keys = context->KeyGen();
        if (operation == "multiply") {
            context->EvalMultKeyGen(keys.secretKey);
        } else if (operation == "sum") {
            const auto rotation_indices =
                FIDESlib::CKKS::GetAccumulateRotationIndices(
                    4, 1, static_cast<int>(batch_size));
            context->EvalRotateKeyGen(
                keys.secretKey,
                std::vector<int32_t>(
                    rotation_indices.begin(), rotation_indices.end()));
        }
        context->LoadContext(keys.publicKey);

        auto left_plaintext = context->MakeCKKSPackedPlaintext(left);
        Ciphertext left_ciphertext = context->Encrypt(keys.publicKey, left_plaintext);
        he_gpu::FidesBackend backend(context);
        Ciphertext result;

        if (operation == "sum") {
            result = backend.sum(left_ciphertext, static_cast<int>(batch_size));
        } else {
            auto right_plaintext = context->MakeCKKSPackedPlaintext(right);
            Ciphertext right_ciphertext =
                context->Encrypt(keys.publicKey, right_plaintext);
            if (operation == "add") {
                result = backend.add(left_ciphertext, right_ciphertext);
            } else if (operation == "subtract") {
                result = backend.subtract(left_ciphertext, right_ciphertext);
            } else {
                result = backend.multiply(left_ciphertext, right_ciphertext);
            }
        }

        fideslib::Plaintext decrypted;
        const auto decrypt_result = context->Decrypt(keys.secretKey, result, &decrypted);
        if (!decrypt_result.isValid) {
            throw std::runtime_error("FIDESlib decryption failed");
        }
        decrypted->SetLength(result_length);
        auto values = decrypted->GetRealPackedValue();
        values.resize(result_length);
        print_result(operation, values);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "he-gpu-demo: " << error.what() << '\n';
        return 1;
    }
}
