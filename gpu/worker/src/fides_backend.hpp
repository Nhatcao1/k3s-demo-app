#pragma once

#include <fideslib.hpp>

namespace he_gpu {

class FidesBackend {
  public:
    explicit FidesBackend(fideslib::CryptoContext<fideslib::DCRTPoly> context);

    fideslib::Ciphertext<fideslib::DCRTPoly> add(
        const fideslib::Ciphertext<fideslib::DCRTPoly>& left,
        const fideslib::Ciphertext<fideslib::DCRTPoly>& right) const;

    fideslib::Ciphertext<fideslib::DCRTPoly> subtract(
        const fideslib::Ciphertext<fideslib::DCRTPoly>& left,
        const fideslib::Ciphertext<fideslib::DCRTPoly>& right) const;

    fideslib::Ciphertext<fideslib::DCRTPoly> multiply(
        const fideslib::Ciphertext<fideslib::DCRTPoly>& left,
        const fideslib::Ciphertext<fideslib::DCRTPoly>& right) const;

    fideslib::Ciphertext<fideslib::DCRTPoly> square(
        const fideslib::Ciphertext<fideslib::DCRTPoly>& encrypted) const;

    fideslib::Ciphertext<fideslib::DCRTPoly> sum(
        const fideslib::Ciphertext<fideslib::DCRTPoly>& encrypted,
        int valid_count) const;

    fideslib::Ciphertext<fideslib::DCRTPoly> mean(
        const fideslib::Ciphertext<fideslib::DCRTPoly>& encrypted,
        int valid_count) const;

  private:
    fideslib::CryptoContext<fideslib::DCRTPoly> context_;
};

}  // namespace he_gpu
