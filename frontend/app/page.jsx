"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    const token = localStorage.getItem("PRED_TOKEN");
    if (token) router.push("/dashboard");
    else router.push("/login");
  }, [router]);
  return <div className="text-center mt-24 text-gray-400">Redirecting…</div>;
}
