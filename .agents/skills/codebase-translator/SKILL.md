---
name: codebase-translator
id: codebase-translator
title: Codebase Internationalization & Localization Specialist
version: 1.0.0
category: workflow
status: active
triggers:
  - "translate codebase"
  - "add new language"
  - "i18n localization"
  - "translate project"
  - "add language support"
requirements:
  - read_file
  - edit_file
  - grep
  - list_dir
  - bash
description: >-
  Autonomous software internationalization and localization engine for codebases.
  Discovers existing multi-language architectures (TypeScript dictionaries, JSON locale trees,
  gettext, Edge normalizers), guarantees 100% key parity with zero missing keys, strictly locks
  variable placeholders ({token}), and propagates language support across full-stack monorepo tiers.
---

# Codebase Internationalization & Localization Specialist Skill

This skill guides Emiliano when acting as a **Principal Internationalization (i18n) & Localization (l10n) Software Engineer**. It provides standard operating procedures for discovering, synthesizing, injecting, and verifying translations across programs, frontend applications, backend APIs, and monorepos.

--------------------------------------------------------------------------------

## 1. System Architecture & Workflow

```
+-------------------------------------------------------------------------+
|                  Codebase Translator Autonomous Pipeline                |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| Phase 1: i18n Archetype & Language Discovery                            |
| • Search for locale directories, i18n registries, and translation files |
| • Identify all existing languages & ISO/BCP 47 codes                    |
| • Extract reference source language schema (typically English 'en')     |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| Phase 2: Schema Extraction & Variable Token Lock                        |
| • Extract 100% of reference dictionary keys                             |
| • Lock variable tokens: {name}, {count}, %s, ${val} - NEVER translate  |
| • Catalog domain-specific terminology (e.g. karaoke=Taki, price=chani)  |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| Phase 3: Cultural & Linguistic Synthesis                                |
| • Synthesize authentic, grammatically sound translations               |
| • Preserve pluralization rules and context-appropriate register         |
| • Respect cultural nuances and formal vs informal address               |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| Phase 4: Multi-Tier Propagation & Surgical Injection                    |
| • Shared Core: Update translation maps, types & language options        |
| • Normalization: Register ISO code in normalizeLang / BCP 47 mappings   |
| • Backend / API: Add checkout copy, email & push notification templates |
| • Admin / UI: Add selector options with proper country/region flag      |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| Phase 5: Verification & Quality Gates                                   |
| • Gate 1: Key Parity Check (missing_keys == 0)                         |
| • Gate 2: Token Integrity Check (no translated or broken placeholders)  |
| • Gate 3: AST & Syntax Check (tsc --noEmit or linter clean exit 0)      |
+-------------------------------------------------------------------------+
```

--------------------------------------------------------------------------------

## 2. Strict Core Rules

### Rule 1: Zero Missing Keys (Key Parity Gate)
Every translation dictionary for the target language MUST have identical keys to the source reference language.
$$\text{keys}(\text{target}) \equiv \text{keys}(\text{source})$$
Never leave a key empty, commented out, or omitted. If a term is an untranslated brand name or technical acronym (e.g., "PlaatoOS", "Stripe", "BLIK", "SMS"), preserve the key and keep the brand noun intact.

### Rule 2: Strict Variable Token Locking
Placeholders in string templates must NEVER be translated, modified, or re-spaced.
- **Allowed**: `"Welcome to {businessName}!"` -> Quechua: `"{businessName}-man allin hamusqayki!"`
- **FORBIDDEN**: `"{negocioNombre}-man allin hamusqayki!"` (Corrupts variable interpolation!).
- Token patterns to protect:
  - Bracketed: `{var}`, `{0}`, `{count}`, `{businessName}`, `{hours}`
  - Printf style: `%s`, `%d`, `%.2f`
  - Template literals: `${item}`

### Rule 3: TypeScript AST & Syntax Preservation
When modifying `.ts` or `.tsx` files:
- Maintain matching quotation styles and escaping.
- Never introduce syntax errors such as unescaped single quotes inside single-quoted strings (e.g., `'don\'t'` or `"don't"`).
- Update type unions when dictionaries are typed with string literal unions:
  ```typescript
  // Before:
  export const translationsMap: Record<'english' | 'spanish', Translation> = ...
  // After:
  export const translationsMap: Record<'english' | 'spanish' | 'quechua', Translation> = ...
  ```

### Rule 4: Multi-Tier Propagation Protocol
In full-stack monorepos, adding a language touches more than one file:
1. **Core Language Registry**: `contexts/language.tsx` or `i18n/config.ts` (options list, flag emoji, display name).
2. **Code Normalizer**: `utils/languageCode.ts` or middleware helpers (mapping word `'quechua'` -> ISO `'qu'`).
3. **UI Dictionaries**: Component navigation, block strings, and common button copy.
4. **Backend Communications**: Email templates, SMS/Push templates, and Stripe checkout labels.
5. **Admin Settings**: Dropdown options for business/tenant configuration.

--------------------------------------------------------------------------------

## 3. Linguistic Reference: Peruvian Quechua (Runasimi)

When targeting Peruvian Quechua (*Runasimi*, ISO `qu` / `quz`):
- **Display Name**: `Runasimi (Quechua)`
- **Flag**: `🇵🇪`
- **ISO 639-1**: `qu`
- **Key Domain Terms in Hospitality & Entertainment**:
  - Song / Sing / Karaoke: **Taki** / **Takiy** (*Takina Wasi* = Karaoke Room / Venue)
  - Price / Cost / Rate: **Chani** (*Chani / ura* = Price per hour)
  - Hour / Time / Schedule: **Pacha** / **Ura** (*Hayk'aq pacha* = Time slot)
  - Reserve / Book: **Waqaychay** (*Churay*)
  - Welcome / Greetings: **Allillanchu** / **Napaykullayki**
  - Closed: **Wichqasqa**
  - Open: **Kichasqa**
  - Room / Venue: **Uku** / **Wasi**
  - Drinks / Cocktails: **Upyanakuna**
  - Days: *Lunes* (Killachaw), *Martes* (Atipachaw), *Miércoles* (Qoyllurchaw), *Jueves* (Illaapachaw), *Viernes* (Ch'askachaw), *Sábado* (K'uychichaw), *Domingo* (Intichaw).
