#!/bin/sh
set -eu

if [ "$#" -ne 4 ]; then
	printf '%s\n' 'usage: verify-pair.sh CERTIFICATE PRIVATE_KEY TRUSTED_CA DNS_NAME' >&2
	exit 2
fi

certificate=$1
private_key=$2
trusted_ca=$3
dns_name=$4
minimum_remaining_seconds=${SCREEN_TRANSLATION_TLS_MIN_REMAINING_SECONDS:-86400}

openssl x509 -in "$certificate" -noout -checkend "$minimum_remaining_seconds" >/dev/null
subject_alt_names=$(openssl x509 -in "$certificate" -noout -ext subjectAltName 2>/dev/null) || {
	printf '%s\n' '証明書にSubject Alternative Nameがありません。' >&2
	exit 1
}
if ! printf '%s\n' "$subject_alt_names" | grep -q 'DNS:'; then
	printf '%s\n' '証明書にDNS Subject Alternative Nameがありません。' >&2
	exit 1
fi
openssl x509 -in "$certificate" -noout -checkhost "$dns_name" >/dev/null
openssl verify -CAfile "$trusted_ca" "$certificate" >/dev/null

certificate_public_key=$(openssl x509 -in "$certificate" -pubkey -noout | openssl pkey -pubin -outform DER | sha256sum | cut -d ' ' -f 1)
private_public_key=$(openssl pkey -in "$private_key" -pubout -outform DER | sha256sum | cut -d ' ' -f 1)
if [ "$certificate_public_key" != "$private_public_key" ]; then
	printf '%s\n' '証明書と秘密鍵が一致しません。' >&2
	exit 1
fi

printf '%s\n' 'TLS証明書・鍵・名前・期限・信頼鎖を確認しました。'
