'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Activity, Mail, Lock, CheckCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';
import { Toaster } from '@/components/ui/sonner';
import { auth, ApiError } from '@/lib/api';
import Loader from '@/app/components/Loader';

export default function Register() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [errors, setErrors] = useState({ email: '', password: '', confirmPassword: '' });

  const validate = () => {
    const newErrors = { email: '', password: '', confirmPassword: '' };
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
    } else if (password.length < 8) {
      newErrors.password = 'Password must be at least 8 characters';
      isValid = false;
    }

    if (!confirmPassword) {
      newErrors.confirmPassword = 'Please confirm your password';
      isValid = false;
    } else if (password !== confirmPassword) {
      newErrors.confirmPassword = 'Passwords do not match';
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
      // Call register (lib/api.ts). It currently doesn't return a token.
      await auth.register(email, password);

      // After successful registration, log the user in to get a token and persist it.
      // auth.login stores the token (localStorage.setItem('token', ...)) per your api.ts
      await auth.login(email, password);

      setSuccess(true);
      toast.success('Registration successful! Redirecting...');

      // short delay so user can see success toast/animation
      setTimeout(() => {
        router.push('/dashboard');
      }, 700);
    } catch (err: any) {
      if (err instanceof ApiError) {
        toast.error(err.message || 'Registration failed');
      } else {
        const msg =
          err?.message ||
          err?.detail ||
          (err?.response && JSON.stringify(err.response)) ||
          'Registration failed. Please try again.';
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
          <h1 className="text-3xl font-bold text-[var(--text-primary)] mb-2">Create Account</h1>
          <p className="text-[var(--text-secondary)]">Start predicting market movements today</p>
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

            <div>
              <label htmlFor="confirmPassword" className="text-sm text-[var(--text-muted)] mb-2 block">
                Confirm Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-[var(--text-muted)]" />
                <Input
                  id="confirmPassword"
                  type="password"
                  placeholder="••••••••"
                  value={confirmPassword}
                  onChange={(e) => {
                    setConfirmPassword(e.target.value);
                    setErrors((prev) => ({ ...prev, confirmPassword: '' }));
                  }}
                  className={`pl-10 bg-[var(--card-bg)] border-[var(--border-subtle)] text-[var(--text-primary)] ${
                    errors.confirmPassword ? 'border-[var(--error-red)]' : ''
                  }`}
                  aria-invalid={!!errors.confirmPassword}
                  aria-describedby={errors.confirmPassword ? 'confirm-password-error' : undefined}
                />
              </div>
              {errors.confirmPassword && (
                <p id="confirm-password-error" className="text-sm text-[var(--error-red)] mt-1">
                  {errors.confirmPassword}
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
                  <span className="ml-2">Creating account...</span>
                </>
              ) : success ? (
                <>
                  <CheckCircle className="h-5 w-5 mr-2" />
                  Success!
                </>
              ) : (
                'Create Account'
              )}
            </Button>
          </form>

          <div className="mt-6 text-center">
            <p className="text-sm text-[var(--text-secondary)]">
              Already have an account?{' '}
              <Link href="/login" className="text-[var(--neon-cyan)] hover:underline font-medium">
                Sign in
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
