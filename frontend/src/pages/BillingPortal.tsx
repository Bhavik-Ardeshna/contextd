import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/api';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';

export default function BillingPortal() {
  const navigate = useNavigate();
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    redirectToPortal();
  }, []);

  const redirectToPortal = async () => {
    try {
      const response = await apiClient.post('/billing/portal-session', {
        return_url: `${window.location.origin}/organization/settings`
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to create portal session');
      }

      const data = await response.json();

      // Redirect to Stripe Customer Portal
      window.location.href = data.portal_url;
    } catch (error) {
      console.error('Failed to create portal session:', error);
      toast.error('Failed to open billing portal. Please try again.');
      navigate('/organization/settings');
    }
  };

  return (
    <div className="flex h-screen items-center justify-center">
      <div className="text-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary mx-auto mb-4" />
        <p className="text-muted-foreground">Redirecting to billing portal...</p>
      </div>
    </div>
  );
}
