'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Activity, LogOut, User } from 'lucide-react';
import { auth } from '@/lib/api';
import { useEffect, useState } from 'react';

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<{ email: string } | null>(null);

  useEffect(() => {
    const userData = auth.getUser();
    setUser(userData);
  }, []);

  const handleLogout = () => {
    auth.logout();
    router.push('/login');
  };

  const isActive = (path: string) => pathname === path;

  return (
    <nav className="sticky top-0 z-50 w-full border-b border-[var(--border-subtle)] bg-[var(--glass-bg)] backdrop-blur-lg">
      <div className="container mx-auto px-4">
        <div className="flex h-16 items-center justify-between">
          <div className="flex items-center gap-8">
            <Link
              href="/"
              className="flex items-center gap-2 transition-all hover:opacity-80"
            >
              <Activity className="h-6 w-6 text-[var(--neon-cyan)]" />
              <span className="text-xl font-bold neon-text">Predictor AI</span>
            </Link>

            <div className="hidden md:flex items-center gap-1">
              <Link
                href="/dashboard"
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                  isActive('/dashboard')
                    ? 'bg-[var(--neon-cyan)] text-[var(--dark-navy)] shadow-lg'
                    : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--card-bg)]'
                }`}
              >
                Dashboard
              </Link>
              {/* <Link
                href="/predictor"
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                  isActive('/predictor')
                    ? 'bg-[var(--neon-cyan)] text-[var(--dark-navy)] shadow-lg'
                    : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--card-bg)]'
                }`}
              >
                Predictor
              </Link> */}
            </div>
          </div>

          <div className="flex items-center gap-3">
            {user ? (
              <div className="flex items-center gap-3">
                <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--card-bg)]">
                  <User className="h-4 w-4 text-[var(--neon-cyan)]" />
                  <span className="text-sm text-[var(--text-secondary)]">
                    Hi, <span className="text-[var(--text-primary)]">{user.email.split('@')[0]}</span>
                  </span>
                </div>
                <button
                  onClick={handleLogout}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-[var(--text-secondary)] hover:text-[var(--error-red)] hover:bg-[var(--card-bg)] transition-all"
                  aria-label="Logout"
                >
                  <LogOut className="h-4 w-4" />
                  <span className="hidden sm:inline">Logout</span>
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <Link
                  href="/login"
                  className="px-4 py-2 rounded-lg text-sm font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--card-bg)] transition-all"
                >
                  Login
                </Link>
                <Link
                  href="/register"
                  className="px-4 py-2 rounded-lg text-sm font-medium bg-[var(--neon-cyan)] text-[var(--dark-navy)] hover:shadow-lg hover:shadow-[var(--neon-cyan-glow)] transition-all"
                >
                  Register
                </Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
