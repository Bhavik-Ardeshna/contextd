import React, { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiClient } from "@/lib/api";
import { useToast } from "@/components/ui/use-toast";

interface SlackTokenDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: (connectionId: string) => void;
}

export function SlackTokenDialog({
  open,
  onOpenChange,
  onSuccess,
}: SlackTokenDialogProps) {
  const [token, setToken] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { toast } = useToast();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!token.trim()) {
      toast({
        title: "Token required",
        description: "Please enter a Slack API token",
        variant: "destructive",
      });
      return;
    }

    setIsSubmitting(true);

    try {
      const response = await apiClient.post("/connections/direct-token/slack", {
        token: token,
        name: "Connection to Slack",
      });

      const data = await response.json();

      toast({
        title: "Connection successful",
        description: "Successfully connected to Slack using the provided token",
      });

      if (data?.id) {
        onSuccess(data.id);
      }

      onOpenChange(false);
    } catch {
      toast({
        title: "Connection failed",
        description: "Failed to connect to Slack with the provided token",
        variant: "destructive",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>Connect to Slack with Token</DialogTitle>
          <DialogDescription>
            For local development, enter your Slack API token directly.
            You can generate a token from the <a href="https://api.slack.com/apps/" target="_blank" rel="noopener noreferrer" className="underline text-primary hover:opacity-80">Slack API website</a>.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <div className="grid gap-4 py-4">
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="slack-token" className="col-span-4">
                Slack API Token
              </Label>
              <Input
                id="slack-token"
                className="col-span-4"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="xoxp-..."
                required
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Connecting..." : "Connect"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
