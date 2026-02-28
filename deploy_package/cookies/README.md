# Cookies Directory

This directory stores Facebook session cookies for each account.

## File Naming

Each account should have its own cookie file named after the account UID:
- `61564814922126.json` - for account with UID 61564814922126
- `61565141970429.json` - for account with UID 61565141970429

## Cookie Format

Cookies must be in Playwright's storage state format:

```json
{
  "cookies": [
    {
      "name": "c_user",
      "value": "YOUR_USER_ID",
      "domain": ".facebook.com",
      "path": "/",
      "expires": 1735689600,
      "httpOnly": false,
      "secure": true,
      "sameSite": "None"
    },
    {
      "name": "xs",
      "value": "YOUR_XS_VALUE",
      "domain": ".facebook.com",
      "path": "/",
      "expires": 1735689600,
      "httpOnly": true,
      "secure": true,
      "sameSite": "None"
    },
    {
      "name": "datr",
      "value": "YOUR_DATR_VALUE",
      "domain": ".facebook.com",
      "path": "/",
      "expires": 1735689600,
      "httpOnly": true,
      "secure": true,
      "sameSite": "None"
    }
  ],
  "origins": []
}
```

## Important Cookies

The most important Facebook cookies are:
- `c_user` - Your user ID
- `xs` - Session token
- `datr` - Device token
- `sb` - Secure browsing token
- `fr` - Facebook tracking token

## How to Get Cookies

See `MANUAL_LOGIN_GUIDE.md` for detailed instructions on exporting cookies from your browser.

## Security

⚠️ **Never commit these files to git!**

Cookie files are already in `.gitignore` to prevent accidental commits.
