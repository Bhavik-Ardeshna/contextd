import { SyncProgressUpdate } from '@/stores/syncStateStore';

export type DerivedSyncStatus = 'completed' | 'failed' | 'cancelled' | 'in_progress' | 'cancelling' | 'pending';

/**
 * Derive the sync status from live progress and database status
 * This ensures consistent status across all components
 */
export function deriveSyncStatus(
    liveProgress: SyncProgressUpdate | undefined,
    hasActiveSubscription: boolean,
    latestSyncJobStatus?: string
): DerivedSyncStatus {
    // If we have live progress, derive status from it
    if (liveProgress) {
        if (liveProgress.is_failed) {
            return 'failed';
        } else if (liveProgress.is_complete) {
            return 'completed';
        } else if (hasActiveSubscription) {
            return 'in_progress';
        }
    }

    // Fall back to database status
    const status = latestSyncJobStatus?.toLowerCase();
    switch (status) {
        case 'completed':
        case 'failed':
        case 'cancelled':
        case 'in_progress':
            return status as DerivedSyncStatus;
        case 'running':
            return 'in_progress';
        case 'cancelling':
            return 'cancelling';
        case 'created':
        case 'pending':
            return 'pending';
        default:
            return 'pending';
    }
}

/**
 * Get the color class for a sync status
 */
export function getSyncStatusColorClass(status: DerivedSyncStatus): string {
    switch (status) {
        case 'completed':
            return 'bg-green-500';
        case 'failed':
        case 'cancelled':
            return 'bg-red-500';
        case 'in_progress':
        case 'cancelling':
            return 'bg-blue-500 animate-pulse';
        case 'pending':
            return 'bg-amber-500';
        default:
            return 'bg-gray-500';
    }
}

/**
 * Get display text for a sync status
 */
export function getSyncStatusDisplayText(status: DerivedSyncStatus): string {
    switch (status) {
        case 'in_progress':
            return 'Running';
        case 'cancelling':
            return 'Cancelling';
        case 'cancelled':
            return 'Cancelled';
        case 'completed':
            return 'Completed';
        case 'failed':
            return 'Failed';
        case 'pending':
            return 'Pending';
        default:
            return 'Not run';
    }
}
