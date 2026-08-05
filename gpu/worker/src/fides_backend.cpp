#include "fides_backend.hpp"

#include <stdexcept>
#include <utility>

namespace he_gpu {

// This is the complete high-level GPU HE function layer. Each public method
// validates its inputs and maps directly to one FIDESlib operation. Keep HTTP,
// file transport, serialization, and key loading in main.cpp and app.py.
FidesBackend::FidesBackend(
    fideslib::CryptoContext<fideslib::DCRTPoly> context)
    : context_(std::move(context)) {
    if (!context_) {
        throw std::invalid_argument("FIDESlib context must not be null");
    }
}

fideslib::Ciphertext<fideslib::DCRTPoly> FidesBackend::add(
    const fideslib::Ciphertext<fideslib::DCRTPoly>& left,
    const fideslib::Ciphertext<fideslib::DCRTPoly>& right) const {
    if (!left || !right) {
        throw std::invalid_argument("add requires two ciphertexts");
    }
    // Ciphertext + ciphertext; no multiplication depth is consumed.
    return context_->EvalAdd(left, right);
}

fideslib::Ciphertext<fideslib::DCRTPoly> FidesBackend::subtract(
    const fideslib::Ciphertext<fideslib::DCRTPoly>& left,
    const fideslib::Ciphertext<fideslib::DCRTPoly>& right) const {
    if (!left || !right) {
        throw std::invalid_argument("subtract requires two ciphertexts");
    }
    // Ciphertext - ciphertext; no multiplication depth is consumed.
    return context_->EvalSub(left, right);
}

fideslib::Ciphertext<fideslib::DCRTPoly> FidesBackend::multiply(
    const fideslib::Ciphertext<fideslib::DCRTPoly>& left,
    const fideslib::Ciphertext<fideslib::DCRTPoly>& right) const {
    if (!left || !right) {
        throw std::invalid_argument("multiply requires two ciphertexts");
    }
    // Ciphertext * ciphertext; multiplication/relinearization keys are loaded
    // by main.cpp before this function is called.
    return context_->EvalMult(left, right);
}

fideslib::Ciphertext<fideslib::DCRTPoly> FidesBackend::sum(
    const fideslib::Ciphertext<fideslib::DCRTPoly>& encrypted,
    int valid_count) const {
    if (!encrypted) {
        throw std::invalid_argument("sum requires one ciphertext");
    }
    if (valid_count < 1) {
        throw std::invalid_argument("valid_count must be positive for sum");
    }
    // Reduce only the valid packed slots; rotation keys are loaded by main.cpp.
    return context_->AccumulateSum(encrypted, valid_count);
}

}  // namespace he_gpu
