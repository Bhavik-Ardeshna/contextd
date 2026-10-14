import React, { useState } from 'react';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Loader2, CheckCircle2, XCircle, CloudUpload } from 'lucide-react';
import { toast } from 'sonner';
import { apiClient } from '@/lib/api';

interface S3ConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

interface S3Config {
  aws_access_key_id: string;
  aws_secret_access_key: string;
  bucket_name: string;
  bucket_prefix: string;
  aws_region: string;
  endpoint_url: string;
  use_ssl: boolean;
}

type Step = 'configure' | 'testing' | 'success';

export function S3ConfigModal({ isOpen, onClose, onSuccess }: S3ConfigModalProps) {
  const [step, setStep] = useState<Step>('configure');
  const [isLoading, setIsLoading] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  const [config, setConfig] = useState<S3Config>({
    aws_access_key_id: '',
    aws_secret_access_key: '',
    bucket_name: '',
    bucket_prefix: 'contextd-outbound/',
    aws_region: 'us-east-1',
    endpoint_url: '',
    use_ssl: true,
  });

  const handleTestConnection = async () => {
    setIsLoading(true);
    setTestResult(null);

    try {
      // Clean config - remove endpoint_url if empty
      const testConfig = {
        ...config,
        endpoint_url: config.endpoint_url.trim() || null,
      };

      const response = await apiClient.post('/s3/test', testConfig);

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Connection test failed');
      }

      const result = await response.json();
      setTestResult({ success: true, message: result.message });
      setStep('testing');
    } catch (error: any) {
      setTestResult({
        success: false,
        message: error.message || 'Failed to connect to S3',
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleSaveConfiguration = async () => {
    setIsLoading(true);

    try {
      // Clean config
      const saveConfig = {
        ...config,
        endpoint_url: config.endpoint_url.trim() || null,
      };

      const response = await apiClient.post('/s3/configure', saveConfig);

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to save configuration');
      }

      const result = await response.json();
      setStep('success');
      toast.success('S3 destination configured successfully');

      // Call onSuccess callback after short delay
      setTimeout(() => {
        onSuccess?.();
        onClose();
      }, 2000);
    } catch (error: any) {
      toast.error(error.message || 'Failed to save S3 configuration');
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    setStep('configure');
    setTestResult(null);
    onClose();
  };

  const isFormValid = () => {
    return (
      config.aws_access_key_id.trim() !== '' &&
      config.aws_secret_access_key.trim() !== '' &&
      config.bucket_name.trim() !== ''
    );
  };

  return (
    <Dialog open={isOpen} onOpenChange={handleClose}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CloudUpload className="h-5 w-5 text-blue-500" />
            Configure S3
          </DialogTitle>
          <DialogDescription>
            Set up S3-compatible storage for streaming and archival
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6">
          {step === 'configure' && (
            <>
              <div className="space-y-4">
                {/* AWS Credentials */}
                <div className="space-y-2">
                  <Label htmlFor="aws_access_key_id">AWS Access Key ID *</Label>
                  <Input
                    id="aws_access_key_id"
                    type="text"
                    placeholder="AKIAIOSFODNN7EXAMPLE"
                    value={config.aws_access_key_id}
                    onChange={(e) =>
                      setConfig({ ...config, aws_access_key_id: e.target.value })
                    }
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="aws_secret_access_key">AWS Secret Access Key *</Label>
                  <Input
                    id="aws_secret_access_key"
                    type="password"
                    placeholder="wJalrXUtnFEMI/K7MDENG/..."
                    value={config.aws_secret_access_key}
                    onChange={(e) =>
                      setConfig({ ...config, aws_secret_access_key: e.target.value })
                    }
                  />
                </div>

                {/* Bucket Configuration */}
                <div className="space-y-2">
                  <Label htmlFor="bucket_name">Bucket Name *</Label>
                  <Input
                    id="bucket_name"
                    type="text"
                    placeholder="my-company-contextd-events"
                    value={config.bucket_name}
                    onChange={(e) => setConfig({ ...config, bucket_name: e.target.value })}
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="bucket_prefix">Bucket Prefix</Label>
                    <Input
                      id="bucket_prefix"
                      type="text"
                      placeholder="contextd-outbound/"
                      value={config.bucket_prefix}
                      onChange={(e) =>
                        setConfig({ ...config, bucket_prefix: e.target.value })
                      }
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="aws_region">AWS Region</Label>
                    <Input
                      id="aws_region"
                      type="text"
                      placeholder="us-east-1"
                      value={config.aws_region}
                      onChange={(e) => setConfig({ ...config, aws_region: e.target.value })}
                    />
                  </div>
                </div>

                {/* Advanced Options */}
                <details className="space-y-2">
                  <summary className="cursor-pointer text-sm font-medium text-gray-600 dark:text-gray-400">
                    Advanced Options (MinIO, LocalStack, etc.)
                  </summary>
                  <div className="mt-2 space-y-2">
                    <Label htmlFor="endpoint_url">Custom Endpoint URL</Label>
                    <Input
                      id="endpoint_url"
                      type="text"
                      placeholder="http://localhost:9000 (leave empty for AWS S3)"
                      value={config.endpoint_url}
                      onChange={(e) =>
                        setConfig({ ...config, endpoint_url: e.target.value })
                      }
                    />
                    <p className="text-xs text-gray-500">
                      For MinIO, LocalStack, or Cloudflare R2. Leave empty for AWS S3.
                    </p>

                    <div className="flex items-center gap-2 mt-4">
                      <input
                        type="checkbox"
                        id="use_ssl"
                        checked={config.use_ssl}
                        onChange={(e) => setConfig({ ...config, use_ssl: e.target.checked })}
                        className="rounded"
                      />
                      <Label htmlFor="use_ssl" className="cursor-pointer">
                        Use SSL/TLS (recommended for production)
                      </Label>
                    </div>
                  </div>
                </details>

                {testResult && !testResult.success && (
                  <Alert variant="destructive">
                    <XCircle className="h-4 w-4" />
                    <AlertDescription>{testResult.message}</AlertDescription>
                  </Alert>
                )}
              </div>

              <div className="flex justify-end gap-3">
                <Button variant="outline" onClick={handleClose}>
                  Cancel
                </Button>
                <Button
                  onClick={handleTestConnection}
                  disabled={!isFormValid() || isLoading}
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Testing Connection...
                    </>
                  ) : (
                    'Test Connection'
                  )}
                </Button>
              </div>
            </>
          )}

          {step === 'testing' && testResult?.success && (
            <>
              <Alert className="border-green-500 bg-green-50 dark:bg-green-950">
                <CheckCircle2 className="h-4 w-4 text-green-600" />
                <AlertDescription className="text-green-600">
                  {testResult.message}
                </AlertDescription>
              </Alert>

              <div className="space-y-3 text-sm">
                <p className="font-medium">Configuration Summary:</p>
                <div className="space-y-1 text-gray-600 dark:text-gray-400">
                  <p>• Bucket: {config.bucket_name}</p>
                  <p>• Region: {config.aws_region}</p>
                  <p>• Prefix: {config.bucket_prefix}</p>
                  {config.endpoint_url && <p>• Endpoint: {config.endpoint_url}</p>}
                </div>
                <p className="text-gray-500 dark:text-gray-400 mt-4">
                  Once configured, all future syncs will automatically write data to the
                  ContextD search index and S3 event storage.
                </p>
              </div>

              <div className="flex justify-end gap-3">
                <Button variant="outline" onClick={() => setStep('configure')}>
                  Back to Edit
                </Button>
                <Button onClick={handleSaveConfiguration} disabled={isLoading}>
                  {isLoading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Saving...
                    </>
                  ) : (
                    'Save Configuration'
                  )}
                </Button>
              </div>
            </>
          )}

          {step === 'success' && (
            <div className="flex flex-col items-center justify-center py-8 space-y-4">
              <CheckCircle2 className="h-16 w-16 text-green-500" />
              <div className="text-center space-y-2">
                <h3 className="text-lg font-semibold">S3 Destination Configured!</h3>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  All future syncs will automatically write to S3
                </p>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
