#include <algorithm>
#include <atomic>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <utility>
#include <vector>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <fideslib.hpp>
#include "CKKS/AccumulateBroadcast.cuh"

#include "fides_backend.hpp"

namespace py = pybind11;

namespace {

using Ciphertext = fideslib::Ciphertext<fideslib::DCRTPoly>;
using Context = fideslib::CryptoContext<fideslib::DCRTPoly>;
using KeyPair = fideslib::KeyPair<fideslib::DCRTPoly>;

std::atomic<std::uint64_t> next_session_id{1};

class NativeCiphertext {
  public:
    NativeCiphertext(Ciphertext value, std::uint64_t session_id)
        : value_(std::move(value)), session_id_(session_id) {
        if (!value_) {
            throw std::invalid_argument("FIDESlib ciphertext must not be null");
        }
    }

  private:
    friend class NativeSession;
    Ciphertext value_;
    std::uint64_t session_id_;
};

class NativeSession {
  public:
    NativeSession(
        int device,
        std::uint32_t multiplicative_depth,
        std::uint32_t first_modulus_size,
        std::uint32_t scaling_modulus_size,
        std::uint32_t ring_dimension,
        std::uint32_t batch_size)
        : session_id_(next_session_id.fetch_add(1)), batch_size_(batch_size) {
        if (device < 0) {
            throw std::invalid_argument("device must be non-negative");
        }
        if (batch_size == 0) {
            throw std::invalid_argument("batch_size must be positive");
        }

        fideslib::CCParams<fideslib::CryptoContextCKKSRNS> parameters;
        parameters.SetMultiplicativeDepth(multiplicative_depth);
        parameters.SetFirstModSize(first_modulus_size);
        parameters.SetScalingModSize(scaling_modulus_size);
        parameters.SetScalingTechnique(fideslib::FLEXIBLEAUTO);
        parameters.SetSecurityLevel(fideslib::HEStd_128_classic);
        parameters.SetRingDim(ring_dimension);
        parameters.SetBatchSize(batch_size);
        parameters.SetDevices({device});
        parameters.SetPlaintextAutoload(false);
        parameters.SetCiphertextAutoload(true);

        context_ = fideslib::GenCryptoContext(parameters);
        context_->Enable(fideslib::PKE);
        context_->Enable(fideslib::KEYSWITCH);
        context_->Enable(fideslib::LEVELEDSHE);
        context_->Enable(fideslib::ADVANCEDSHE);

        keys_ = context_->KeyGen();
        context_->EvalMultKeyGen(keys_.secretKey);
        const auto rotations = FIDESlib::CKKS::GetAccumulateRotationIndices(
            4, 1, static_cast<int>(batch_size_));
        context_->EvalRotateKeyGen(
            keys_.secretKey,
            std::vector<std::int32_t>(rotations.begin(), rotations.end()));
        context_->LoadContext(keys_.publicKey);
        backend_ = std::make_unique<he_gpu::FidesBackend>(context_);
    }

    NativeSession(const NativeSession&) = delete;
    NativeSession& operator=(const NativeSession&) = delete;

    ~NativeSession() { close(); }

    std::shared_ptr<NativeCiphertext> encrypt(std::vector<double> values) {
        require_open();
        if (values.empty() || values.size() > batch_size_) {
            throw std::invalid_argument(
                "encrypt value count must be between 1 and batch_size");
        }
        values.resize(batch_size_, 0.0);
        auto plaintext = context_->MakeCKKSPackedPlaintext(values);
        auto encrypted = context_->Encrypt(keys_.publicKey, plaintext);
        return wrap(std::move(encrypted));
    }

    std::vector<double> decrypt(
        const std::shared_ptr<NativeCiphertext>& encrypted,
        std::size_t length) {
        require_open();
        auto& value = require_ciphertext(encrypted);
        if (length == 0 || length > batch_size_) {
            throw std::invalid_argument(
                "decrypt length must be between 1 and batch_size");
        }
        fideslib::Plaintext plaintext;
        auto ciphertext = value.value_;
        const auto result = context_->Decrypt(
            keys_.secretKey, ciphertext, &plaintext);
        if (!result.isValid || !plaintext) {
            throw std::runtime_error("FIDESlib decryption failed");
        }
        plaintext->SetLength(length);
        auto values = plaintext->GetRealPackedValue();
        if (values.size() < length) {
            throw std::runtime_error(
                "FIDESlib returned fewer plaintext slots than requested");
        }
        values.resize(length);
        return values;
    }

    std::shared_ptr<NativeCiphertext> add(
        const std::shared_ptr<NativeCiphertext>& left,
        const std::shared_ptr<NativeCiphertext>& right) {
        require_open();
        return wrap(backend_->add(
            require_ciphertext(left).value_, require_ciphertext(right).value_));
    }

    std::shared_ptr<NativeCiphertext> subtract(
        const std::shared_ptr<NativeCiphertext>& left,
        const std::shared_ptr<NativeCiphertext>& right) {
        require_open();
        return wrap(backend_->subtract(
            require_ciphertext(left).value_, require_ciphertext(right).value_));
    }

    std::shared_ptr<NativeCiphertext> multiply(
        const std::shared_ptr<NativeCiphertext>& left,
        const std::shared_ptr<NativeCiphertext>& right) {
        require_open();
        return wrap(backend_->multiply(
            require_ciphertext(left).value_, require_ciphertext(right).value_));
    }

    std::shared_ptr<NativeCiphertext> square(
        const std::shared_ptr<NativeCiphertext>& encrypted) {
        require_open();
        return wrap(backend_->square(require_ciphertext(encrypted).value_));
    }

    std::shared_ptr<NativeCiphertext> sum(
        const std::shared_ptr<NativeCiphertext>& encrypted,
        int valid_count) {
        require_open();
        return wrap(backend_->sum(
            require_ciphertext(encrypted).value_, valid_count));
    }

    std::shared_ptr<NativeCiphertext> mean(
        const std::shared_ptr<NativeCiphertext>& encrypted,
        int valid_count) {
        require_open();
        return wrap(backend_->mean(
            require_ciphertext(encrypted).value_, valid_count));
    }

    std::shared_ptr<NativeCiphertext> variance(
        const std::shared_ptr<NativeCiphertext>& encrypted,
        int valid_count) {
        require_open();
        return wrap(backend_->variance(
            require_ciphertext(encrypted).value_, valid_count));
    }

    void close() noexcept {
        if (closed_) {
            return;
        }
        backend_.reset();
        keys_.secretKey.reset();
        keys_.publicKey.reset();
        context_.reset();
        closed_ = true;
    }

  private:
    void require_open() const {
        if (closed_ || !context_ || !backend_) {
            throw std::runtime_error("FIDES native session is closed");
        }
    }

    NativeCiphertext& require_ciphertext(
        const std::shared_ptr<NativeCiphertext>& encrypted) const {
        if (!encrypted) {
            throw std::invalid_argument("operation requires a ciphertext");
        }
        if (encrypted->session_id_ != session_id_) {
            throw std::invalid_argument(
                "ciphertext belongs to a different FIDES native session");
        }
        return *encrypted;
    }

    std::shared_ptr<NativeCiphertext> wrap(Ciphertext encrypted) const {
        return std::make_shared<NativeCiphertext>(
            std::move(encrypted), session_id_);
    }

    std::uint64_t session_id_;
    std::size_t batch_size_;
    Context context_;
    KeyPair keys_;
    std::unique_ptr<he_gpu::FidesBackend> backend_;
    bool closed_ = false;
};

}  // namespace

PYBIND11_MODULE(_native, module) {
    module.doc() = "Native FIDESlib backend for he-sdk";
    module.attr("__engine_version__") =
        "fideslib-2.1.3-patched-openfhe-1.5.1.1";

    py::class_<NativeCiphertext, std::shared_ptr<NativeCiphertext>>(
        module, "Ciphertext");

    py::class_<NativeSession>(module, "NativeSession")
        .def(
            py::init<int, std::uint32_t, std::uint32_t, std::uint32_t,
                     std::uint32_t, std::uint32_t>(),
            py::arg("device") = 0,
            py::arg("multiplicative_depth") = 3,
            py::arg("first_modulus_size") = 60,
            py::arg("scaling_modulus_size") = 50,
            py::arg("ring_dimension") = 16384,
            py::arg("batch_size") = 8192)
        .def("encrypt", &NativeSession::encrypt)
        .def("decrypt", &NativeSession::decrypt)
        .def("add", &NativeSession::add)
        .def("subtract", &NativeSession::subtract)
        .def("multiply", &NativeSession::multiply)
        .def("square", &NativeSession::square)
        .def("sum", &NativeSession::sum)
        .def("mean", &NativeSession::mean)
        .def("variance", &NativeSession::variance)
        .def("close", &NativeSession::close);
}
