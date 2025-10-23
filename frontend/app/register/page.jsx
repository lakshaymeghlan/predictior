"use client";
import { useState } from "react";
import { register } from "../../../lib/api";
import { useRouter } from "next/navigation";
import Loader from "../components/Loader";

export default function RegisterPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const router = useRouter();

  const onSubmit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const data = await register({ email, password });
      if (data.access_token) {
        localStorage.setItem("PRED_TOKEN", data.access_token);
        router.push("/dashboard");
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <form onSubmit={onSubmit} className="w-full max-w-md bg-gray-800 p-6 rounded-2xl shadow-lg">
        <h2 className="text-2xl font-semibold mb-4">Create account</h2>
        {err && <div className="text-rose-400 mb-3">{err}</div>}
        <label className="block mb-2 text-sm text-gray-400">Email</label>
        <input className="w-full p-3 rounded bg-gray-900 border border-gray-700 mb-3"
               value={email} onChange={(e)=>setEmail(e.target.value)} />
        <label className="block mb-2 text-sm text-gray-400">Password</label>
        <input type="password" className="w-full p-3 rounded bg-gray-900 border border-gray-700 mb-4"
               value={password} onChange={(e)=>setPassword(e.target.value)} />
        <div className="flex items-center justify-between">
          <button className="px-4 py-2 bg-rose-500 rounded" disabled={busy}>
            {busy ? <Loader size={6}/> : "Register"}
          </button>
          <a href="/login" className="text-sm text-gray-400">Already have an account?</a>
        </div>
      </form>
    </div>
  );
}
