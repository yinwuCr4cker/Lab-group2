# C++ Lab Assignment Notes

## Current Setup

- The app uses 10 QCM questions only.
- QCM score: 50 points.
- Coding lab score: 50 points.
- Total score: 100 points.
- The coding labs were not changed.
- The app stores submissions in Supabase only.
- Local SQLite storage was removed.

## QCM Topics

The 10 QCM questions are intermediate-level C++ questions related to:

- Variables
- Data types: `int`, `float`, `char`, `bool`
- Constants and literals
- Basic input/output using `cin` and `cout`
- Arithmetic operators
- Integer division
- Modulo operator
- Operator precedence
- Type casting for floating-point division

## Lab Section

The lab section is still worth 50 points total and contains 3 labs:

- Lab 1 - Declare & Display
- Lab 2 - Calculator
- Lab 3 - Constants Challenge

The lab instructions, starter code, and grading checks were kept the same except for fixing broken text display.

## Text Fixes

Broken encoded text was removed from the app.

Example of old broken text:

```text
Lab 3 â€” Constants Challenge ðŸ”¥
```

Correct English text now shown:

```text
Lab 3 - Constants Challenge
```

All visible app text is now English ASCII text only.

## Storage Fix

The app no longer creates or uses:

```text
lab_results.db
```

Supabase is required. The app needs these secrets:

```text
SUPABASE_URL
SUPABASE_KEY
```

If Supabase is not configured, the app shows a clear English error message.

## Proxy Fix

The app was failing because Python requests tried to use this broken proxy:

```text
http://127.0.0.1:9
```

Supabase and Telegram bot requests were changed to ignore local proxy environment variables.

## Quick Check Message Fix

The message:

```text
No code submitted (starter code unchanged)
```

now displays with:

- Green background
- Black border
- Black readable text

This fixes the issue where white text appeared on a white background.

## Verification

The app source was checked for:

- Valid Python syntax
- No non-ASCII characters
- No local SQLite database files
- Supabase connectivity
