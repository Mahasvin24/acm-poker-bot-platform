"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";

import { acceptInvitation, declineInvitation, listInvitations } from "./api";
import styles from "./account.module.css";
import type { Account, MatchInvitation } from "./types";

export function InvitationInbox({ account }: { account: Account }) {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const [invitations, setInvitations] = useState<MatchInvitation[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const rows = await listInvitations();
        if (active) { setInvitations(rows); setLoadError(null); }
      } catch (reason) {
        if (active) setLoadError(reason instanceof Error ? reason.message : "Could not load invitations.");
      }
    };
    void load();
    const interval = window.setInterval(() => void load(), 3_000);
    return () => { active = false; window.clearInterval(interval); };
  }, []);

  const respond = async (invitation: MatchInvitation, accept: boolean, name?: string) => {
    setBusy(invitation.match_id);
    setError(null);
    try {
      if (accept) {
        await acceptInvitation(invitation.match_id, name);
        dialog.current?.close();
        router.push(`/match/${encodeURIComponent(invitation.match_id)}`);
      } else {
        await declineInvitation(invitation.match_id);
        setInvitations((current) => current.filter((item) => item.match_id !== invitation.match_id));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not respond. Try again.");
    } finally {
      setBusy(null);
    }
  };

  const accept = (event: FormEvent<HTMLFormElement>, invitation: MatchInvitation) => {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("display_name") ?? "").trim();
    void respond(invitation, true, name || undefined);
  };

  if (invitations.length === 0 && !loadError) return null;

  return (
    <>
      <button className={`${styles.secondaryButton} ${styles.inviteInboxButton}`} onClick={() => dialog.current?.showModal()} type="button">Invites ({invitations.length})</button>
      <dialog className={styles.invitationDialog} ref={dialog} aria-labelledby="invitation-heading">
        <div className={styles.invitationHeading}>
          <h2 id="invitation-heading">Match invitations</h2>
          <button className={styles.textButton} onClick={() => dialog.current?.close()} type="button">Close</button>
        </div>
        <p className={styles.fieldHint}>Join directly—no code needed. A seat is yours once you accept.</p>
        {(error || loadError) && <p className={styles.formError} role="alert">{error || loadError}</p>}
        {invitations.map((invitation) => (
          <form className={styles.invitationItem} key={invitation.match_id} onSubmit={(event) => accept(event, invitation)} aria-label={`Invitation to ${invitation.match_name}`}>
            <h3>{invitation.match_name}</h3>
            {account.participant_kind !== "bot" ? (
              <div className={styles.field}>
                <label htmlFor={`invite-name-${invitation.match_id}`}>Table name</label>
                <input defaultValue={account.display_name ?? account.email.split("@")[0]} id={`invite-name-${invitation.match_id}`} name="display_name" maxLength={80} required />
              </div>
            ) : <p className={styles.fieldHint}>Your saved bot will join. Make sure it has passed its connection test.</p>}
            <div className={styles.panelActions}>
              <button className={styles.primaryButton} disabled={busy !== null} type="submit">{busy === invitation.match_id ? "Working…" : "Accept"}</button>
              <button className={styles.secondaryButton} disabled={busy !== null} onClick={() => void respond(invitation, false)} type="button">Decline</button>
            </div>
          </form>
        ))}
      </dialog>
    </>
  );
}
