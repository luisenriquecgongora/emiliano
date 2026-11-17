"""
Unit tests for Emiliano Local Privacy Vault & Zero-PII Rehydrator.
"""

from emiliano.core.privacy_vault import PrivacyVault, VaultCategory


def test_detects_and_masks_credentials():
    vault = PrivacyVault()
    text = (
        "Setup keys: openai=sk-proj-1234567890abcdefghijklmnopqrstuvwxyzABCDEF "
        "and aws=AKIAIOSFODNN7EXAMPLE and github=ghp_1234567890abcdefghijklmnopqrstuvwxyz"
    )
    sanitized, report = vault.anonymize(text)

    assert "sk-proj-" not in sanitized
    assert "AKIAIOSFODNN7EXAMPLE" not in sanitized
    assert "ghp_1234567890" not in sanitized
    assert "__VAULT_SECRET_OPENAI_1__" in sanitized
    assert "__VAULT_SECRET_AWS_1__" in sanitized
    assert "__VAULT_SECRET_GITHUB_1__" in sanitized
    assert report.zero_leakage_guaranteed is True

    # Rehydrate
    restored = vault.rehydrate(sanitized)
    assert restored == text


def test_detects_financial_and_uk_pii():
    vault = PrivacyVault()
    text = (
        "Customer Alice: email=alice.smith@monzo.co.uk, "
        "NINO=QQ 12 34 56 A, "
        "IBAN=GB29NWBK60161331926819, "
        "Phone=+44 7911 123456"
    )
    sanitized, report = vault.anonymize(text)

    assert "alice.smith@monzo.co.uk" not in sanitized
    assert "QQ 12 34 56 A" not in sanitized
    assert "GB29NWBK60161331926819" not in sanitized
    assert "+44 7911 123456" not in sanitized

    assert "__VAULT_PII_EMAIL_1__" in sanitized
    assert "__VAULT_PII_UK_NINO_1__" in sanitized
    assert "__VAULT_FIN_IBAN_1__" in sanitized
    assert "__VAULT_PII_PHONE_1__" in sanitized

    # Verify zero leakage
    ok, leaks = vault.assert_zero_leakage(sanitized)
    assert ok is True
    assert len(leaks) == 0

    # Rehydrate
    restored = vault.rehydrate(sanitized)
    assert restored == text


def test_referential_consistency():
    """Identical entities across messages/paragraphs must receive the same surrogate token."""
    vault = PrivacyVault()
    text = (
        "Notify user bob@revolut.com of transaction. "
        "If bob@revolut.com does not respond, re-send to bob@revolut.com."
    )
    sanitized, report = vault.anonymize(text)

    # All 3 occurrences must map to the exact same surrogate token
    assert sanitized.count("__VAULT_PII_EMAIL_1__") == 3
    assert "__VAULT_PII_EMAIL_2__" not in sanitized

    restored = vault.rehydrate(sanitized)
    assert restored == text


def test_zero_leakage_assertion():
    vault = PrivacyVault()
    secret = "sk-proj-9999999999abcdefghijklmnopqrstuvwxyzABCDEF"
    vault.register_secret_literal(secret, category=VaultCategory.SECRET_OPENAI)

    # Sanitized string
    safe_text = "The key is __VAULT_SECRET_OPENAI_1__"
    ok, leaks = vault.assert_zero_leakage(safe_text)
    assert ok is True
    assert len(leaks) == 0

    # Unsafe string with leaked raw secret
    leaked_text = f"Leaked: {secret}"
    ok, leaks = vault.assert_zero_leakage(leaked_text)
    assert ok is False
    assert len(leaks) == 1
    assert "SECRET_OPENAI" in leaks[0]


def test_sanitize_messages_structure():
    vault = PrivacyVault()
    messages = [
        {"role": "system", "content": "You are a customer assistant for support@monzo.com."},
        {"role": "user", "content": "Charge client with IBAN GB29NWBK60161331926819."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "charge_account",
                        "arguments": '{"iban": "GB29NWBK60161331926819", "email": "support@monzo.com"}',
                    },
                }
            ],
        },
    ]

    sanitized, report = vault.sanitize_messages(messages)
    assert report.entities_detected >= 2
    assert "support@monzo.com" not in sanitized[0]["content"]
    assert "GB29NWBK60161331926819" not in sanitized[1]["content"]
    assert "GB29NWBK60161331926819" not in sanitized[2]["tool_calls"][0]["function"]["arguments"]

    # Rehydrate tool call arguments
    tool_args = sanitized[2]["tool_calls"][0]["function"]["arguments"]
    restored_args = vault.rehydrate(tool_args)
    assert "GB29NWBK60161331926819" in restored_args
    assert "support@monzo.com" in restored_args


def test_custom_domain_patterns():
    vault = PrivacyVault()
    # Register internal NHS patient ID format: NHS-123-456-7890
    vault.register_custom_pattern("nhs_number", r"\bNHS-[0-9]{3}-[0-9]{3}-[0-9]{4}\b")

    text = "Record for patient NHS-987-654-3210 updated."
    sanitized, report = vault.anonymize(text)

    assert "NHS-987-654-3210" not in sanitized
    assert "__VAULT_CUSTOM_1__" in sanitized

    restored = vault.rehydrate(sanitized)
    assert restored == text
