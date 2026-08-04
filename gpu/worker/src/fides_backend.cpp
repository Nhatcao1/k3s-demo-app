#include "fides_backend.hpp"

#include <stdexcept>
#include <utility>

namespace he_gpu {

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
    return context_->EvalAdd(left, right);
}

fideslib::Ciphertext<fideslib::DCRTPoly> FidesBackend::subtract(
    const fideslib::Ciphertext<fideslib::DCRTPoly>& left,
    const fideslib::Ciphertext<fideslib::DCRTPoly>& right) const {
    if (!left || !right) {
        throw std::invalid_argument("subtract requires two ciphertexts");
    }
    return context_->EvalSub(left, right);
}

fideslib::Ciphertext<fideslib::DCRTPoly> FidesBackend::multiply(
    const fideslib::Ciphertext<fideslib::DCRTPoly>& left,
    const fideslib::Ciphertext<fideslib::DCRTPoly>& right) const {
    if (!left || !right) {
        throw std::invalid_argument("multiply requires two ciphertexts");
    }
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
    return context_->AccumulateSum(encrypted, valid_count);
}

}  // namespace he_gpu
