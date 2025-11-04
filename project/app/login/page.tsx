'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Activity, Mail, Lock, CheckCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';
import { Toaster } from '@/components/ui/sonner';
import { auth, ApiError } from '@/lib/api'; // <- using your new api.ts
import Loader from '@/app/components/Loader';

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [errors, setErrors] = useState({ email: '', password: '' });

  const validate = () => {
    const newErrors = { email: '', password: '' };
    let isValid = true;

    if (!email) {
      newErrors.email = 'Email is required';
      isValid = false;
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      newErrors.email = 'Invalid email format';
      isValid = false;
    }

    if (!password) {
      newErrors.password = 'Password is required';
      isValid = false;
    } else if (password.length < 6) {
      newErrors.password = 'Password must be at least 6 characters';
      isValid = false;
    }

    setErrors(newErrors);
    return isValid;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!validate()) return;

    setLoading(true);
    try {
      // auth.login from your lib/api.ts: stores token in localStorage and returns AuthResponse
      await auth.login(email, password);

      setSuccess(true);
      toast.success('Login successful!');

      // short delay for success state
      setTimeout(() => {
        router.push('/dashboard');
      }, 600);
    } catch (err: any) {
      // If ApiError, show its message; otherwise fallback to generic
      if (err instanceof ApiError) {
        toast.error(err.message || 'Login failed');
      } else {
        // try to extract useful message from common shapes
        const msg =
          err?.message ||
          err?.detail ||
          (err?.response && JSON.stringify(err.response)) ||
          'Login failed. Please check your credentials.';
        toast.error(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--dark-navy)] px-4">
      <Toaster position="top-right" theme="dark" />

      <div className="w-full max-w-md animate-slide-up">
        <div className="text-center mb-8">
          <Link href="/" className="inline-flex items-center gap-2 mb-6 hover:opacity-80 transition-opacity">
            <Activity className="h-8 w-8 text-[var(--neon-cyan)]" />
            <span className="text-2xl font-bold neon-text">Predictor AI</span>
          </Link>
          <h1 className="text-3xl font-bold text-[var(--text-primary)] mb-2">Welcome Back</h1>
          <p className="text-[var(--text-secondary)]">Sign in to access your dashboard</p>
        </div>

        <div className="glass-card p-8">
          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label htmlFor="email" className="text-sm text-[var(--text-muted)] mb-2 block">
                Email Address
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-[var(--text-muted)]" />
                <Input
                  id="email"
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value);
                    setErrors((prev) => ({ ...prev, email: '' }));
                  }}
                  className={`pl-10 bg-[var(--card-bg)] border-[var(--border-subtle)] text-[var(--text-primary)] ${
                    errors.email ? 'border-[var(--error-red)]' : ''
                  }`}
                  aria-invalid={!!errors.email}
                  aria-describedby={errors.email ? 'email-error' : undefined}
                />
              </div>
              {errors.email && (
                <p id="email-error" className="text-sm text-[var(--error-red)] mt-1">
                  {errors.email}
                </p>
              )}
            </div>

            <div>
              <label htmlFor="password" className="text-sm text-[var(--text-muted)] mb-2 block">
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-[var(--text-muted)]" />
                <Input
                  id="password"
                  type="password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    setErrors((prev) => ({ ...prev, password: '' }));
                  }}
                  className={`pl-10 bg-[var(--card-bg)] border-[var(--border-subtle)] text-[var(--text-primary)] ${
                    errors.password ? 'border-[var(--error-red)]' : ''
                  }`}
                  aria-invalid={!!errors.password}
                  aria-describedby={errors.password ? 'password-error' : undefined}
                />
              </div>
              {errors.password && (
                <p id="password-error" className="text-sm text-[var(--error-red)] mt-1">
                  {errors.password}
                </p>
              )}
            </div>

            <Button
              type="submit"
              disabled={loading || success}
              className={`w-full font-semibold transition-all ${
                success
                  ? 'bg-[var(--success-green)] hover:bg-[var(--success-green)]'
                  : 'bg-[var(--neon-cyan)] hover:shadow-lg hover:shadow-[var(--neon-cyan-glow)]'
              } text-[var(--dark-navy)]`}
            >
              {loading ? (
                <>
                  <Loader size="sm" />
                  <span className="ml-2">Signing in...</span>
                </>
              ) : success ? (
                <>
                  <CheckCircle className="h-5 w-5 mr-2" />
                  Success!
                </>
              ) : (
                'Sign In'
              )}
            </Button>
          </form>

          <div className="mt-6 text-center">
            <p className="text-sm text-[var(--text-secondary)]">
              Don't have an account?{' '}
              <Link
                href="/register"
                className="text-[var(--neon-cyan)] hover:underline font-medium"
              >
                Sign up
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
