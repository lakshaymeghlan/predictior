// app/components/AuthGuard.tsx
'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Loader from './Loader';
import { auth } from '@/lib/api';

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // on mount check auth
    const ok = auth && typeof auth.isAuthenticated === 'function' ? auth.isAuthenticated() : false;
    if (!ok) {
      // if not authenticated, still allow page to render but show loader
      // (change behavior if you want redirect to login)
      setReady(false);
      // short delay then consider guest (to avoid hydration mismatch)
      setTimeout(() => setReady(true), 250);
      return;
    }
    setReady(true);
  }, [router]);

  if (!ready) {
    return <Loader fullScreen />;
  }

  return <>{children}</>;
}
