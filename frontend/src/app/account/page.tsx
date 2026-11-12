import { AuthPage } from "@/features/account/auth-page";

export const metadata = { title: "Account | ACM Poker" };

export default async function AccountPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string | string[] }>;
}) {
  const { next = "" } = await searchParams;
  return <AuthPage next={Array.isArray(next) ? next[0] ?? "" : next} />;
}
