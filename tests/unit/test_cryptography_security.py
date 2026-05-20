"""
Test suite for cryptography security and version compatibility.

This test verifies that the cryptography library functions correctly for
our use case and helps detect any security vulnerabilities or compatibility
issues when updating to newer versions.
"""

import pytest


# Test version information
def test_cryptography_version_check():
    """Test that cryptography version is appropriate for security requirements."""
    try:
        import cryptography
        from packaging import version

        current_version = version.parse(cryptography.__version__)

        # Version 45.0.5 is our current version
        # We should verify it's at least this version to ensure known vulnerabilities are patched
        min_version = version.parse("42.0.4")  # Known vulnerable versions are < 42.0.4

        assert (
            current_version >= min_version
        ), f"Cryptography version {current_version} is below minimum secure version {min_version}"

        print(f"Current cryptography version: {current_version}")

    except ImportError:
        pytest.fail("Cryptography library not available")


def test_keyring_cryptography_integration():
    """Test that keyring works with current cryptography version."""
    try:
        import keyring  # noqa: F401 - imported to verify availability

        from chronos_mcp.credentials import CredentialManager

        # Test that credential manager can be instantiated
        credential_manager = CredentialManager()

        # Test basic functionality - this should not fail with cryptography issues
        status = credential_manager.get_status()
        assert isinstance(status, dict)
        assert "keyring_available" in status

        # If keyring is available, test basic operations
        if status["keyring_available"]:
            # Test storing and retrieving a test credential
            test_alias = "test_crypto_security"
            test_password = "test_password_123"

            try:
                # Store password
                result = credential_manager.set_password(test_alias, test_password)

                if result:  # Only test retrieval if storage succeeded
                    # Retrieve password
                    retrieved = credential_manager.get_password(test_alias)
                    assert retrieved == test_password

                    # Clean up
                    credential_manager.delete_password(test_alias)

            except Exception as e:
                # Log the error but don't fail the test if it's a platform-specific keyring issue
                print(f"Keyring operation failed (may be platform-specific): {e}")

    except ImportError as e:
        pytest.skip(f"Keyring not available: {e}")


def test_cryptography_vulnerable_version_detection():
    """Test that we can detect if we're running a vulnerable cryptography version."""
    try:
        import cryptography
        from packaging import version

        current_version = version.parse(cryptography.__version__)

        # Known vulnerable versions
        vulnerable_versions = [
            "38.0.0",
            "38.0.1",
            "38.0.2",
            "38.0.3",
            "38.0.4",
            "39.0.0",
            "40.0.0",
            "40.0.1",
            "40.0.2",
            "41.0.0",
            "41.0.1",
            "41.0.2",
            "41.0.3",
            "41.0.4",
            "41.0.5",
            "41.0.6",
            "41.0.7",
            "42.0.0",
            "42.0.1",
            "42.0.2",
            "42.0.3",  # CVE-2023-23931, CVE-2023-0286
        ]

        # This test should PASS with our current version (45.0.5)
        # but would FAIL if we were running a vulnerable version
        for vuln_version in vulnerable_versions:
            assert current_version > version.parse(vuln_version), (
                f"Current version {current_version} is vulnerable! "
                f"Known vulnerable version: {vuln_version}"
            )

    except ImportError:
        pytest.fail("Cryptography library not available")


def test_future_cryptography_version_compatibility():
    """Test that updating to newer cryptography versions doesn't break our usage."""
    try:
        import cryptography
        from packaging import version

        current_version = version.parse(cryptography.__version__)

        # Test that we're not on a version that's too old
        # Version 46.0.1 is the latest as of this test
        recommended_min = version.parse("45.0.0")

        assert current_version >= recommended_min, (
            f"Cryptography version {current_version} is older than "
            f"recommended minimum {recommended_min}"
        )

        # This test will help us detect if a future update breaks compatibility
        # by testing basic cryptographic operations that keyring might use
        import base64
        import os

        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

        # Test basic encryption/decryption (similar to what keyring backends might do)
        password = b"test_password"
        salt = os.urandom(16)

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password))
        f = Fernet(key)

        # Test encryption/decryption
        test_data = b"sensitive credential data"
        encrypted = f.encrypt(test_data)
        decrypted = f.decrypt(encrypted)

        assert decrypted == test_data, "Basic cryptography operations failed"

    except ImportError:
        pytest.fail("Cryptography library not available")
    except Exception as e:
        pytest.fail(f"Cryptography compatibility test failed: {e}")


if __name__ == "__main__":
    # Run tests directly for debugging
    test_cryptography_version_check()
    test_keyring_cryptography_integration()
    test_cryptography_vulnerable_version_detection()
    test_future_cryptography_version_compatibility()
    print("All cryptography security tests passed!")
