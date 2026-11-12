# OpenChromLab — Release & Publishing SOP (Standard Operating Procedure)

This document outlines the standard procedure for implementing changes, verifying test parity, maintaining the clean `release` branch, updating documentation, and publishing GitHub Releases for OpenChromLab.

---

## 1. Branch Strategy

The repository maintains two primary branches:

1. **`main` (Development & Ground-Truth Testbed):**
   * Contains complete codebase + full 26 MB `test-set/` (11 authentic `.D` Agilent reaction runs, `.rx` ground-truth data, `.ch` raw delta files, and `MPZ_Reaction_Summary.xlsx`).
   * Used for daily engineering, automated verification, and ground-truth parity testing.
2. **`release` (Clean Public Release & Deployment):**
   * Contains the exact identical application codebase, UI assets, and automated build scripts, **WITHOUT** `test-set/`.
   * Minimal ~1.2 MB footprint.
   * Source for downloadable release source zips and tagged binary releases.

---

## 2. Standard Workflow for Any New Changes

Whenever completing a feature, bugfix, or visual refinement:

### Step 1: Run Full 4-Tier Automated Verification
Always verify all tests pass (134/134) before committing:
```bash
xvfb-run -a python3 tests/run_e2e_tests.py
```
*(On native Windows: `py tests/run_e2e_tests.py`)*

### Step 2: Keep Documentation Aligned
* Keep [`README.md`](file:///home/antigravity/piezoperny/OpenChromLab/README.md) updated:
  * Application header with embedded logo: `<img src="agilent_ui/logo.png" width="42" height="42" align="center" alt="OpenChromLab Logo" /> OpenChromLab`
  * Direct download & release table placed immediately beneath the badges.
  * Version badges matching `APP_VERSION` in [`agilent_ui/splash.py`](file:///home/antigravity/piezoperny/OpenChromLab/agilent_ui/splash.py).
* Keep `APP_VERSION` synchronized across:
  * `agilent_ui/splash.py` (`APP_VERSION = "x.y.z"`)
  * `main.py` (`__version__ = APP_VERSION`)

### Step 3: Commit and Push to `main`
```bash
git checkout main
git add -A
git commit -m "<Clear descriptive message of changes>"
git push origin main
```

---

## 3. Syncing to the Clean `release` Branch

To keep the public `release` branch synchronized without reintroducing `test-set/`:

```bash
git checkout release
git merge main --no-edit
# Ensure test-set is never kept on the release branch:
if [ -d "test-set" ]; then
    git rm -rf test-set
    git commit -m "Keep release branch clean without test-set"
fi
git push origin release
git checkout main
```

---

## 4. Publishing a New Standalone Windows Release (`OpenChromLab.exe`)

Publishing a release is 100% automated via GitHub Actions:

### Step 1: Create and Push an Annotated Version Tag on `release`
```bash
git checkout main
# Point the tag to the clean release branch commit:
git tag -a v1.1.0-beta -m "OpenChromLab v1.1.0 Beta Release" release
git push origin v1.1.0-beta
```
*(If updating an existing tag: `git tag -d <tag> && git push origin :refs/tags/<tag>` first)*

### Step 2: Automated Cloud Compilation & Asset Attachment
Pushing any tag matching `v*` automatically triggers `.github/workflows/build_exe.yml`:
1. Launches a fresh Windows runner on GitHub.
2. Packages standalone `OpenChromLab.exe` with `OpenChromLab.ico` baked into the PE icon header.
3. Automatically creates the GitHub Release on `https://github.com/piezoperny/OpenChromLab/releases`.
4. Attaches `OpenChromLab.exe` directly to the release notes with auto-generated changelogs.

---

## 5. Local Standalone EXE Build (Optional / Offline)

To compile `OpenChromLab.exe` locally on a Windows PC without GitHub:
1. Double-click `build_exe.bat`.
2. Grab the generated standalone `dist\OpenChromLab.exe`.
