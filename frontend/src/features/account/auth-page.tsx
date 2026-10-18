"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import {
  AccountApiError,
  getMe,
  loginAccount,
  registerAccount,
} from "./api";
import styles from "./account.module.css";

type Mode = "login" | "register";

interface AuthPageProps {
  next: string;
}

function safeNext(next: string): string | null {
  return next.startsWith("/") && !next.startsWith("//") ? next : null;
}

function destination(role: "user" | "admin", next: string): string {
  return safeNext(next) ?? (role === "admin" ? "/admin" : "/dashboard");
}

export function AuthPage({ next }: AuthPageProps) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [checking, setChecking] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getMe()
      .then((account) => {
        if (active) router.replace(destination(account.role, next));
      })
      .catch((requestError: unknown) => {
        if (active && !(requestError instanceof AccountApiError && requestError.status === 401)) {
          setError("The account service is unavailable. Check that the API is running.");
        }
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
  }, [next, router]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "").trim();
    const password = String(form.get("password") ?? "");
    const confirmation = String(form.get("confirmation") ?? "");
    if (mode === "register" && password !== confirmation) {
      setError("Passwords do not match. Re-enter the confirmation.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      if (mode === "register") await registerAccount(email, password);
      const account = await loginAccount(email, password);
      router.replace(destination(account.role, next));
    } catch (requestError) {
      setError(
        requestError instanceof AccountApiError
          ? requestError.message
          : "The account service could not be reached. Try again.",
      );
    } finally {
      setPending(false);
    }
  };

  if (checking) {
    return (
      <main className={styles.page} id="main-content">
        <div className={styles.loading}><span>Checking Session</span></div>
      </main>
    );
  }

  return (
    <main className={styles.page} id="main-content">
      <header className={styles.header}>
        <Link className={styles.wordmark} href="/">ACM / POKER</Link>
        <span className={styles.headerTitle}>Account</span>
        <Link className={styles.textButton} href="/demo">Try the Demo</Link>
      </header>
      <div className={styles.authLayout}>
        <section className={styles.authIntro}>
          <div>
            <p className={styles.eyebrow}>One account · Either seat</p>
            <h1>Bring instinct.<br /><em>Or code.</em></h1>
          </div>
          <p>
            Create one account to play in the browser, register your bots, or both. Organizers
            share a short join code for each match.
          </p>
        </section>
        <section className={styles.authPanel} aria-labelledby="account-heading">
          <div className={styles.authCard}>
            <div className={styles.modeTabs} role="tablist" aria-label="Account action">
              <button
                aria-selected={mode === "login"}
                onClick={() => { setMode("login"); setError(null); }}
                role="tab"
                type="button"
              >
                Sign In
              </button>
              <button
                aria-selected={mode === "register"}
                onClick={() => { setMode("register"); setError(null); }}
                role="tab"
                type="button"
              >
                Create Account
              </button>
            </div>
            <h2 id="account-heading">
              {mode === "login" ? "Return to your seat." : "Start with an account."}
            </h2>
            <p>
              {mode === "login"
                ? safeNext(next)?.startsWith("/join")
                  ? "Sign in to finish joining the match."
                  : "Sign in to join a match, manage your bots, or return to a live table."
                : "You will choose to play yourself or seat one of your bots when you join a match."}
            </p>
            <form className={styles.form} onSubmit={submit}>
              <div className={styles.field}>
                <label htmlFor="account-email">Email</label>
                <input
                  autoComplete="email"
                  id="account-email"
                  name="email"
                  placeholder="you@example.com…"
                  required
                  spellCheck={false}
                  type="email"
                />
              </div>
              <div className={styles.field}>
                <label htmlFor="account-password">Password</label>
                <input
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  id="account-password"
                  minLength={10}
                  name="password"
                  placeholder="At least 10 characters…"
                  required
                  type="password"
                />
              </div>
              {mode === "register" && (
                <div className={styles.field}>
                  <label htmlFor="account-confirmation">Confirm Password</label>
                  <input
                    autoComplete="new-password"
                    id="account-confirmation"
                    minLength={10}
                    name="confirmation"
                    placeholder="Repeat your password…"
                    required
                    type="password"
                  />
                </div>
              )}
              {error && <p aria-live="polite" className={styles.formError}>{error}</p>}
              <button className={styles.primaryButton} disabled={pending} type="submit">
                {pending ? "Working…" : mode === "login" ? "Sign In" : "Create Account"}
              </button>
            </form>
          </div>
        </section>
      </div>
    </main>
  );
}
