# Security Policy

## Overview

Chronos MCP takes security seriously. This document outlines our current security posture and ongoing improvements.

## 🔐 Secure Credential Storage

As of v2.0.0, Chronos MCP uses system keyring for secure password storage:
- **macOS**: Keychain Access
- **Windows**: Windows Credential Locker
- **Linux**: Secret Service (GNOME Keyring, KWallet, etc.)

Passwords are no longer stored in plain text. For environments without keyring support (containers, SSH sessions), the system falls back to configuration file storage with clear warnings.

To migrate existing plain text passwords to secure storage:
```bash
python scripts/migrate_to_keyring.py
```

## ⚠️ Known Security Considerations

### 1. Input Validation (In Progress)
- **Issue**: Enhanced input validation for CalDAV URLs and user inputs
- **Impact**: Potential for injection attacks or malformed requests
- **Status**: Basic validation implemented, comprehensive validation planned for v2.1.0

### 2. Rate Limiting (Planned)
- **Issue**: No protection against rapid API calls
- **Impact**: Potential for resource exhaustion
- **Mitigation**: Planned for v2.1.0

## Reporting Security Vulnerabilities

Please report security vulnerabilities via:
1. GitHub Security Advisories (preferred)
2. Email: code-developer@democratize.technology (PGP key available on request)

**Please do not report security issues through public GitHub issues.**

## Security Roadmap

### Version 2.0.0 (Current Release)
- [x] Implement keyring support for credential storage
- [x] Implement secure credential migration tool
- [x] Add basic input validation
- [x] XSS and injection prevention
- [x] Path traversal protection

### Version 2.1.0 (Upcoming)
- [ ] Enhanced input validation for all user inputs
- [ ] Add rate limiting
- [ ] Implement API authentication
- [ ] Add audit logging

## Best Practices

1. **Credential Security**: Use system keyring (automatic in v2.0.0+)
2. **File Permissions**: Ensure `~/.chronos/` has restrictive permissions
3. **Network Security**: Use HTTPS for CalDAV connections when possible
4. **Account Security**: Use app-specific passwords where supported
5. **Regular Updates**: Keep Chronos MCP updated for security patches

## Security Features

- **Credential Management**: System keyring integration with secure fallback
- **Input Sanitization**: Protection against XSS and injection attacks
- **Error Handling**: Sanitized error messages that don't leak sensitive information
- **RFC Compliance**: Validation follows CalDAV and iCalendar standards

## Acknowledgments

We appreciate responsible disclosure of security vulnerabilities.
