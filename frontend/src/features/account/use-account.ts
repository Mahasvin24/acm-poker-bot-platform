"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AccountApiError, getMe } from "./api";
import type { Account } from "./types";

interface AccountState {
  account: Account | null;
  error: string | null;
  reload: () => Promise<void>;
}

/** Load the signed-in account, sending visitors to sign in and back to ``returnTo``. */
export function useAccount(returnTo: string): AccountState {
  const router = useRouter();
  const [account, setAccount] = useState<Account | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const next = await getMe();
    setAccount(next);
    setError(null);
  }, []);

  useEffect(() => {
    let active = true;
    getMe()
      .then((next) => {
        if (active) {
          setAccount(next);
          setError(null);
        }
      })
      .catch((requestError: unknown) => {
        if (!active) return;
        if (requestError instanceof AccountApiError && requestError.status === 401) {
          router.replace(`/account?next=${encodeURIComponent(returnTo)}`);
          return;
        }
        setAccount(null);
        setError(
          requestError instanceof Error
            ? requestError.message
            : "The account service is unavailable.",
        );
      });
    return () => {
      active = false;
    };
  }, [returnTo, router]);

  return { account, error, reload };
}
