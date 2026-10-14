import { useNavigate } from 'react-router-dom';
import { XCircle, ChevronLeft } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTheme } from '@/lib/theme-provider';

export const BillingCancel = () => {
  const navigate = useNavigate();
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo header */}
        <div className="mb-12 text-center">
          <img
            src="/navios.svg"
            alt="ContextD"
            className="h-8 w-auto mx-auto mb-2"
            style={{ maxWidth: '180px' }}
          />
          <p className="text-xs text-muted-foreground">
            Build smarter agents
          </p>
        </div>

        {/* Content */}
        <div className="text-center space-y-8">
          <div className="w-16 h-16 mx-auto rounded-full bg-red-50 dark:bg-red-950/20 flex items-center justify-center">
            <XCircle className="w-8 h-8 text-red-600 dark:text-red-500" />
          </div>

          <div className="space-y-3">
            <h1 className="text-2xl font-normal">Payment Cancelled</h1>
            <p className="text-muted-foreground">
              Your payment was cancelled and no charges were made
            </p>
          </div>

          <div className="space-y-6">
            <p className="text-sm text-muted-foreground">
              You can still use ContextD with limited features, or complete your subscription setup anytime from your organization settings.
            </p>

            <button
              onClick={() => navigate('/')}
              className={cn(
                "w-full flex items-center justify-center space-x-2 px-6 py-3 rounded-lg transition-all",
                "bg-primary text-primary-foreground hover:bg-primary/90"
              )}
            >
              <ChevronLeft className="w-4 h-4" />
              <span>Continue to Dashboard</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default BillingCancel;
