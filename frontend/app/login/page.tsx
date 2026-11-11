"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { login, register } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "register") {
        await register({
          email,
          password,
          full_name: fullName,
          organization_name: orgName,
        });
      }
      await login(email, password);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const input =
    "w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-sky-500";

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/60 p-6">
        <div>
          <h1 className="text-2xl font-bold tracking-wide">THRONEX</h1>
          <p className="text-sm text-zinc-400">
            {mode === "login" ? "Sign in to your workspace" : "Create your workspace"}
          </p>
        </div>
        {mode === "register" && (
          <>
            <input className={input} placeholder="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
            <input className={input} placeholder="Organization name" value={orgName} onChange={(e) => setOrgName(e.target.value)} required />
          </>
        )}
        <input className={input} type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input className={input} type="password" placeholder="Password (min 8 characters)" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required />
        {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
        <button disabled={busy} className="w-full rounded bg-sky-600 py-2 text-sm font-medium hover:bg-sky-500 disabled:opacity-50">
          {busy ? "Please wait..." : mode === "login" ? "Sign in" : "Create account"}
        </button>
        <button type="button" onClick={() => setMode(mode === "login" ? "register" : "login")} className="w-full text-sm text-zinc-400 hover:text-zinc-200">
          {mode === "login" ? "No account? Register" : "Have an account? Sign in"}
        </button>
      </form>
    </main>
  );
}