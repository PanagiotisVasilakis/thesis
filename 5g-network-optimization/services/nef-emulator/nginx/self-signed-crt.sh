#!/bin/bash

# Generate a self-signed SSL certificate with OpenSSL
# Configuration via environment variables (with sensible defaults)

CERT_COUNTRY="${CERT_COUNTRY:-GR}"
CERT_STATE="${CERT_STATE:-Athens}"
CERT_LOCALITY="${CERT_LOCALITY:-Athens}"
CERT_ORG="${CERT_ORG:-NEF-Emulator}"
CERT_ORG_UNIT="${CERT_ORG_UNIT:-Development}"
CERT_CN="${CERT_CN:-localhost}"
CERT_EMAIL="${CERT_EMAIL:-nef@localhost}"
CERT_DAYS="${CERT_DAYS:-365}"

# Check if OpenSSL is installed
if ! [ -x "$(command -v openssl)" ]; then
  echo 'Error: OpenSSL is not installed.' >&2
  exit 1
fi

# Generate a Private Key
openssl genrsa -out /etc/nginx/certs/private_nef.pem 2048

# Generate a CSR (Certificate Signing Request)
openssl req -new -key /etc/nginx/certs/private_nef.pem -out /etc/nginx/certs/server_nef.csr \
  -subj "/C=${CERT_COUNTRY}/ST=${CERT_STATE}/L=${CERT_LOCALITY}/O=${CERT_ORG}/OU=${CERT_ORG_UNIT}/CN=${CERT_CN}/emailAddress=${CERT_EMAIL}"

# Generate a Self Signed Certificate
openssl x509 -req -days "${CERT_DAYS}" -in /etc/nginx/certs/server_nef.csr -signkey /etc/nginx/certs/private_nef.pem -out /etc/nginx/certs/self_signed_nef.pem

echo "Self-signed certificate generated successfully for CN=${CERT_CN}"

