import { useEffect, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Loader2, Mail, Lock, User, Eye, EyeOff } from 'lucide-react';
import { useAuth } from '@/lib/auth-context';
import { useAuth0 } from '@auth0/auth0-react';
import authConfig from '@/config/auth';
import { cn } from '@/lib/utils';

const Login = () => {
  const { login, isAuthenticated, devLogin, devRegister } = useAuth();
  const { loginWithRedirect } = useAuth0();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const invitation = searchParams.get('invitation');
  const organization = searchParams.get('organization');
  const organizationName = searchParams.get('organization_name');

  // Dev auth form state
  const [isSignUp, setIsSignUp] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  // Auth0 redirect for non-dev-auth mode
  useEffect(() => {
    if (authConfig.devAuthEnabled) {
      // Dev auth mode: redirect to dashboard if already authenticated
      if (isAuthenticated) {
        navigate('/', { replace: true });
      }
      return;
    }

    if (!isAuthenticated && authConfig.authEnabled) {
      if (invitation && organization) {
        const redirectOptions = {
          authorizationParams: {
            invitation,
            organization,
          },
          appState: {
            organizationName: organizationName || undefined,
          },
        };

        console.log('Attempting login with invitation. Check Auth0 if this fails.', redirectOptions);

        loginWithRedirect(redirectOptions);
      } else {
        login();
      }
    } else if (!isAuthenticated) {
      login();
    }
  }, [
    isAuthenticated,
    login,
    loginWithRedirect,
    invitation,
    organization,
    organizationName,
    navigate,
  ]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      if (isSignUp) {
        if (password !== confirmPassword) {
          setError('Passwords do not match');
          setLoading(false);
          return;
        }
        if (password.length < 4) {
          setError('Password must be at least 4 characters');
          setLoading(false);
          return;
        }
        const result = await devRegister(email, password, fullName || undefined);
        if (result.success) {
          navigate('/onboarding', { replace: true });
        } else {
          setError(result.error || 'Registration failed');
        }
      } else {
        const result = await devLogin(email, password);
        if (result.success) {
          navigate('/', { replace: true });
        } else {
          setError(result.error || 'Login failed');
        }
      }
    } catch (err) {
      setError('An unexpected error occurred');
    } finally {
      setLoading(false);
    }
  };

  // Dev auth: show login/signup form
  if (authConfig.devAuthEnabled) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-background">
        <div className="w-full max-w-md mx-4">
          <div className="border border-border rounded-xl p-8 bg-card shadow-lg">
            {/* Header */}
            <div className="text-center mb-8">
              <h1 className="text-2xl font-semibold text-foreground">
                {isSignUp ? 'Create Account' : 'Welcome Back'}
              </h1>
              <p className="text-sm text-muted-foreground mt-2">
                {isSignUp
                  ? 'Sign up to get started'
                  : 'Sign in to your account'}
              </p>
              <div className="mt-2 inline-flex items-center px-2 py-1 rounded-md bg-primary/10 text-primary text-xs font-medium">
                Dev Mode
              </div>
            </div>

            {/* Error message */}
            {error && (
              <div className="mb-4 p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-sm">
                {error}
              </div>
            )}

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-4">
              {isSignUp && (
                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-foreground">Full Name</label>
                  <div className="relative">
                    <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <input
                      type="text"
                      placeholder="John Doe"
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      className={cn(
                        "w-full pl-10 pr-4 py-2.5 bg-transparent border rounded-lg text-sm",
                        "focus:outline-none focus:ring-1 focus:ring-primary/50",
                        "placeholder:text-muted-foreground/50"
                      )}
                    />
                  </div>
                </div>
              )}

              <div className="space-y-1.5">
                <label className="text-sm font-medium text-foreground">Email</label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <input
                    type="email"
                    placeholder="you@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    className={cn(
                      "w-full pl-10 pr-4 py-2.5 bg-transparent border rounded-lg text-sm",
                      "focus:outline-none focus:ring-1 focus:ring-primary/50",
                      "placeholder:text-muted-foreground/50"
                    )}
                    autoFocus
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium text-foreground">Password</label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    placeholder="Enter your password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    className={cn(
                      "w-full pl-10 pr-10 py-2.5 bg-transparent border rounded-lg text-sm",
                      "focus:outline-none focus:ring-1 focus:ring-primary/50",
                      "placeholder:text-muted-foreground/50"
                    )}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              {isSignUp && (
                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-foreground">Confirm Password</label>
                  <div className="relative">
                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <input
                      type={showPassword ? 'text' : 'password'}
                      placeholder="Confirm your password"
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      required
                      className={cn(
                        "w-full pl-10 pr-4 py-2.5 bg-transparent border rounded-lg text-sm",
                        "focus:outline-none focus:ring-1 focus:ring-primary/50",
                        "placeholder:text-muted-foreground/50"
                      )}
                    />
                  </div>
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className={cn(
                  "w-full py-2.5 rounded-lg text-sm font-medium transition-colors",
                  "bg-primary text-primary-foreground hover:bg-primary/90",
                  "disabled:opacity-50 disabled:cursor-not-allowed",
                  "flex items-center justify-center gap-2"
                )}
              >
                {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                {isSignUp ? 'Create Account' : 'Sign In'}
              </button>
            </form>

            {/* Toggle sign up / sign in */}
            <div className="mt-6 text-center text-sm text-muted-foreground">
              {isSignUp ? (
                <>
                  Already have an account?{' '}
                  <button
                    onClick={() => { setIsSignUp(false); setError(''); }}
                    className="text-primary hover:underline font-medium"
                  >
                    Sign In
                  </button>
                </>
              ) : (
                <>
                  Don't have an account?{' '}
                  <button
                    onClick={() => { setIsSignUp(true); setError(''); }}
                    className="text-primary hover:underline font-medium"
                  >
                    Sign Up
                  </button>
                </>
              )}
            </div>

            {/* Default credentials hint */}
            {!isSignUp && (
              <div className="mt-4 p-3 rounded-lg bg-muted/50 text-xs text-muted-foreground">
                <p className="font-medium mb-1">Default credentials:</p>
                <p>Email: admin@example.com</p>
                <p>Password: admin</p>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // Auth0 mode: show loading/redirect UI
  return (
    <div className="flex h-screen w-full items-center justify-center bg-background">
      <div className="flex flex-col items-center justify-center space-y-4 text-center">
        <Loader2 className="h-10 w-10 animate-spin text-primary" />
        {organizationName ? (
          <>
            <p className="text-lg font-semibold">
              You've been invited to join {organizationName}
            </p>
            <p className="text-muted-foreground">
              Please log in or sign up to accept the invitation. Redirecting
              you...
            </p>
          </>
        ) : (
          <p className="text-muted-foreground">Redirecting to login...</p>
        )}
      </div>
    </div>
  );
};

export default Login;
