"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

import { requestPasswordReset } from "./api";
import styles from "./account.module.css";

export function ForgotPasswordPage() {
  const [pending, setPending] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("email") ?? "").trim();
    setPending(true);
    setError(null);
    try {
      await requestPasswordReset(email);
      setSubmitted(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "That did not work. Try again.");
    } finally {
      setPending(false);
    }
  };

  return (
    <main className={styles.page} id="main-content">
      <header className={styles.header}>
        <Link className={styles.wordmark} href="/">ACM / POKER</Link>
        <span className={styles.headerTitle}>Account</span>
        <Link className={styles.textButton} href="/account">Sign In</Link>
      </header>
      <div className={styles.narrow}>
        <section className={styles.panel}>
          <p className={styles.sectionLabel}>Password help</p>
          <h2>Forgot your password?</h2>
          {submitted ? (
            <div className={styles.entrantBody}>
              <p className={styles.panelIntro}>
                If an account exists for that email, the match organizer will see a reset request
                on their admin console. Share your email with them if you are at the event now.
              </p>
              <p className={styles.fieldHint}>
                After they reset it, sign in with the temporary password and change it from your dashboard.
              </p>
              <div className={styles.panelActions}>
                <Link className={styles.primaryButton} href="/account">Back to sign in</Link>
              </div>
            </div>
          ) : (
            <form className={styles.form} onSubmit={(event) => void submit(event)}>
              <p className={styles.panelIntro}>
                Enter the email you used to register. We do not send email from this platform;
                your organizer can issue a new password from the admin dashboard.
              </p>
              <div className={styles.field}>
                <label htmlFor="forgot-email">Email</label>
                <input autoComplete="email" id="forgot-email" name="email" required type="email" />
              </div>
              {error && <p className={styles.formError} role="alert">{error}</p>}
              <button className={styles.primaryButton} disabled={pending} type="submit">
                {pending ? "Sending…" : "Request organizer reset"}
              </button>
            </form>
          )}
        </section>
      </div>
    </main>
  );
}
