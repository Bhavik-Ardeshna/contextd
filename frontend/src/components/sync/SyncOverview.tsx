import React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SyncUIMetadata } from "./types";
import { InfoIcon } from "lucide-react";

interface SyncOverviewProps {
  syncMetadata: SyncUIMetadata | null;
}

export function SyncOverview({ syncMetadata }: SyncOverviewProps) {
  if (!syncMetadata) return null;

  const { source, destination } = syncMetadata;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2">
          <InfoIcon className="h-5 w-5 text-primary" />
          ContextD sync plan
        </CardTitle>
        <CardDescription>How this source becomes searchable context</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div className="rounded-md bg-muted p-4">
            <p className="text-sm text-muted-foreground leading-relaxed">
              Data will be synchronized from <span className="font-medium text-foreground">{source.name}</span> to <span className="font-medium text-foreground">{destination.name}</span>.
              ContextD will extract records, normalize facts, attach lineage, and make the result available for search and graph retrieval.
            </p>
            <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
              You can tune the stages before the context is committed.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
