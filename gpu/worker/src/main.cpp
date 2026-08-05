#include <any>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>

#include <ciphertext-ser.h>
#include <cryptocontext-ser.h>
#include <key/key-ser.h>
#include <openfhe.h>
#include <scheme/ckksrns/ckksrns-ser.h>

#include <fideslib.hpp>
#include "CKKS/Ciphertext.cuh"
#include "CKKS/openfhe-interface/RawCiphertext.cuh"

#include "fides_backend.hpp"

// High-level role of this file:
//   gpu/api/app.py writes one request to temporary files and starts this binary.
//   main.cpp loads those files, calls one FidesBackend function, and writes the
//   encrypted result file for the API to return. It does not own HTTP handling
//   and it never receives a secret key or plaintext input.
namespace {

using FidesCiphertext = fideslib::Ciphertext<fideslib::DCRTPoly>;
using FidesContext = fideslib::CryptoContext<fideslib::DCRTPoly>;
using CpuCiphertext = lbcrypto::Ciphertext<lbcrypto::DCRTPoly>;

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

FidesCiphertext load_ciphertext(
    const std::filesystem::path& path,
    const FidesContext& context) {
    // Convert the serialized patched-OpenFHE ciphertext into the wrapper that
    // FIDESlib will load onto the GPU when the selected operation runs.
    CpuCiphertext cpu_ciphertext;
    if (!lbcrypto::Serial::DeserializeFromFile(
            path.string(), cpu_ciphertext, lbcrypto::SerType::BINARY)) {
        throw std::runtime_error("could not deserialize ciphertext");
    }

    // The wrapper owns only FIDESlib's patched OpenFHE ciphertext. The
    // standard openfhe-python runtime never enters this process.
    FidesContext parent = context;
    auto wrapped = std::make_shared<fideslib::CiphertextImpl<fideslib::DCRTPoly>>(
        std::move(parent));
    wrapped->cpu = std::make_any<CpuCiphertext>(std::move(cpu_ciphertext));
    return wrapped;
}

void save_ciphertext(
    const std::filesystem::path& path,
    const FidesContext& context,
    FidesCiphertext result) {
    if (!result || !result->loaded) {
        throw std::runtime_error("FIDESlib produced no GPU ciphertext");
    }

    // Bring the GPU result back into its patched-OpenFHE CPU representation so
    // the trusted client can deserialize and decrypt the returned ciphertext.
    context->Synchronize();
    result->EnsureLazyCPUCopy();
    auto& cpu_ciphertext = std::any_cast<CpuCiphertext&>(result->cpu);
    auto gpu_ciphertext = std::static_pointer_cast<FIDESlib::CKKS::Ciphertext>(
        context->GetDeviceCiphertext(result->gpu));

    FIDESlib::CKKS::RawCipherText raw;
    gpu_ciphertext->store(raw);
    const auto cpu_levels =
        cpu_ciphertext->GetElements().at(0).GetAllElements().size();
    if (cpu_levels < static_cast<std::size_t>(raw.numRes)) {
        throw std::runtime_error("GPU result has more levels than its CPU template");
    }
    FIDESlib::CKKS::GetOpenFHECipherText(cpu_ciphertext, raw);

    if (!lbcrypto::Serial::SerializeToFile(
            path.string(), cpu_ciphertext, lbcrypto::SerType::BINARY)) {
        throw std::runtime_error("could not serialize result ciphertext");
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        // 1. Read file paths and the requested operation from gpu/api/app.py.
        const auto arguments = parse_arguments(argc, argv);
        const auto& operation = required(arguments, "operation");
        const auto& context_path = required(arguments, "context");
        const auto& public_key_path = required(arguments, "public-key");
        const auto& left_path = required(arguments, "left");
        const auto& output_path = required(arguments, "output");

        if (operation != "add" && operation != "subtract" &&
            operation != "multiply" && operation != "sum") {
            throw std::invalid_argument("unsupported operation");
        }

        // 2. Load the HE context, public key, and only the evaluation keys
        // required by this operation. The secret key stays with the client.
        FidesContext context;
        if (!fideslib::Serial::DeserializeFromFile(
                context_path, context, fideslib::BINARY)) {
            throw std::runtime_error("could not deserialize context");
        }

        fideslib::PublicKey<fideslib::DCRTPoly> public_key;
        if (!fideslib::Serial::DeserializeFromFile(
                public_key_path, public_key, fideslib::BINARY)) {
            throw std::runtime_error("could not deserialize public key");
        }

        if (operation == "multiply" || operation == "sum") {
            std::ifstream evaluation_keys(
                required(arguments, "evaluation-keys"), std::ios::binary);
            if (!evaluation_keys) {
                throw std::runtime_error("could not open evaluation keys");
            }
            const bool loaded = operation == "multiply"
                ? context->DeserializeEvalMultKey(evaluation_keys, fideslib::BINARY)
                : context->DeserializeEvalAutomorphismKey(
                      evaluation_keys, fideslib::BINARY);
            if (!loaded) {
                throw std::runtime_error("could not deserialize evaluation keys");
            }
        }

        // 3. Initialize FIDESlib on the GPU and delegate the HE math to the
        // deliberately small function layer in fides_backend.cpp.
        context->LoadContext(public_key);
        he_gpu::FidesBackend backend(context);
        const auto left = load_ciphertext(left_path, context);
        FidesCiphertext result;

        if (operation == "sum") {
            const int valid_count = std::stoi(required(arguments, "valid-count"));
            result = backend.sum(left, valid_count);
        } else {
            const auto right = load_ciphertext(required(arguments, "right"), context);
            if (operation == "add") {
                result = backend.add(left, right);
            } else if (operation == "subtract") {
                result = backend.subtract(left, right);
            } else {
                result = backend.multiply(left, right);
            }
        }

        // 4. Write one encrypted result for gpu/api/app.py to return over HTTP.
        save_ciphertext(output_path, context, result);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "he-gpu-worker: " << error.what() << '\n';
        return 1;
    }
}
