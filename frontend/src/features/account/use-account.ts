"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AccountApiError, getMe } from "./api";
import type { Account } from "./types";

interface AccountState {
  account: Account | null;
  error: string | null;
}

/** Load the signed-in account, sending visitors to sign in and back to ``returnTo``. */
export function useAccount(returnTo: string): AccountState {
  const router = useRouter();
  const [state, setState] = useState<AccountState>({ account: null, error: null });

  useEffect(() => {
    let active = true;
    getMe()
      .then((account) => {
        if (active) setState({ account, error: null });
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof AccountApiError && error.status === 401) {
          router.replace(`/account?next=${encodeURIComponent(returnTo)}`);
          return;
        }
        setState({
          account: null,
          error: error instanceof Error ? error.message : "The account service is unavailable.",
        });
      });
    return () => {
      active = false;
    };
  }, [returnTo, router]);

  return state;
}
