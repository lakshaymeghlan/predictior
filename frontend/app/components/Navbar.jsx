"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { getCurrentUser, logout } from "../lib/api";
import { useRouter } from "next/navigation";

export default function Navbar() {
  const [user, setUser] = useState(null);
  const router = useRouter();

  useEffect(() => {
    const token = localStorage.getItem("PRED_TOKEN");
    if (token) {
      getCurrentUser(token).then(u => setUser(u)).catch(() => setUser(null));
    }
  }, []);

  const handleLogout = () => {
    logout();
    setUser(null);
    router.push("/");
  }

  return (
    <nav className="bg-gray-800 border-b border-gray-700">
      <div className="container mx-auto px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href="/" className="text-xl font-semibold">Predictor</Link>
          <Link href="/predictor" className="text-sm text-gray-300 hover:text-white">Predictor</Link>
          <Link href="/dashboard" className="text-sm text-gray-300 hover:text-white">Dashboard</Link>
        </div>

        <div className="flex items-center gap-4">
          {!user ? (
            <>
              <Link href="/login" className="px-3 py-1 bg-rose-500 rounded text-sm">Login</Link>
              <Link href="/register" className="px-3 py-1 border border-gray-600 rounded text-sm">Register</Link>
            </>
          ) : (
            <>
              <div className="text-sm text-gray-300">Hi, {user.email.split("@")[0]}</div>
              <button onClick={handleLogout} className="px-3 py-1 bg-gray-700 rounded text-sm">Logout</button>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
