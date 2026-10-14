import React, { useEffect, useState } from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import * as VisuallyHidden from '@radix-ui/react-visually-hidden';
import { useCollectionCreationStore } from '@/stores/collectionCreationStore';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { X } from 'lucide-react';
import { toast } from 'sonner';

// Import view components
import { CollectionFormView } from './creation-views/CollectionFormView';
import { SourceSelectView } from './creation-views/SourceSelectView';
import { SourceConfigView } from './creation-views/SourceConfigView';
import { OAuthRedirectView } from './creation-views/OAuthRedirectView';
import { SuccessView } from './creation-views/SuccessView';
import { CollectionVisualization } from './creation-views/CollectionVisualization';

export const CollectionCreationModal: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [humanReadableId, setHumanReadableId] = useState<string>('');

  const {
    isOpen,
    currentStep,
    flowType,
    collectionName,
    existingCollectionName,
    selectedSource,
    sourceName,
    sourceConnectionName,
    closeModal,
    setStep,
    reset,
    isAddingToExistingCollection,
  } = useCollectionCreationStore();

  // Generate human-readable ID when collection name changes (only for new collections)
  useEffect(() => {
    // Only generate for new collections, not when adding to existing
    if (!isAddingToExistingCollection() && collectionName) {
      const generateHumanReadableId = (name: string) => {
        // Convert to lowercase and trim
        let readableId = name.toLowerCase().trim();

        // Remove any character that's not a letter, number, or space
        readableId = readableId.replace(/[^a-z0-9\s]/g, '');

        // Replace spaces with hyphens
        readableId = readableId.replace(/\s+/g, '-');

        // Ensure no consecutive hyphens
        readableId = readableId.replace(/-+/g, '-');

        // Trim hyphens from start and end
        readableId = readableId.replace(/^-+|-+$/g, '');

        // Generate random 6-character alphanumeric suffix
        const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
        let suffix = '';
        for (let i = 0; i < 6; i++) {
          suffix += chars.charAt(Math.floor(Math.random() * chars.length));
        }

        // Combine with suffix
        readableId = `${readableId}-${suffix}`;

        return readableId;
      };

      setHumanReadableId(generateHumanReadableId(collectionName));
    } else if (!isAddingToExistingCollection() && !collectionName) {
      // If collection name is empty, clear the readable ID
      setHumanReadableId('');
    }
  }, [collectionName, isAddingToExistingCollection]);

  // Handle OAuth callback
  useEffect(() => {
    const isOAuthReturn = searchParams.get('oauth_return') === 'true';
    const status = searchParams.get('status');
    const connectionId = searchParams.get('source_connection_id');

    if (isOAuthReturn) {
      if (status === 'success' || status === 'sync_started') {
        // OAuth successful
        if (connectionId) {
          useCollectionCreationStore.getState().setConnectionId(connectionId);
        }

        // Get store data to navigate to collection
        const store = useCollectionCreationStore.getState();
        const collectionId = store.collectionId || store.existingCollectionId;

        if (collectionId) {
          // Close modal and navigate directly to collection detail view
          store.closeModal();

          // Navigate to collection with success params
          navigate(`/collections/${collectionId}?status=success&source_connection_id=${connectionId}`);

          // Reset store state after navigation
          setTimeout(() => {
            store.reset();
          }, 100);

        }
      } else if (status === 'error') {
        // Handle error
        console.error('OAuth error');
      }

      // Clean up URL
      const newUrl = window.location.pathname;
      window.history.replaceState({}, '', newUrl);
    }
  }, [searchParams, navigate]);

  const handleClose = () => {
    // Don't close during OAuth redirect
    if (currentStep === 'oauth-redirect') {
      return;
    }

    // Clear URL params
    const newUrl = window.location.pathname;
    window.history.replaceState({}, '', newUrl);

    // Close the modal immediately - this MUST set isOpen to false
    closeModal();

    // Reset state after modal is fully closed (animation complete)
    // This prevents the "stateless" modal issue
    setTimeout(() => {
      reset();
    }, 500); // Increased delay to ensure modal is fully closed
  };

  const renderCurrentView = () => {
    // For add-to-collection flow only, skip collection form
    if (isAddingToExistingCollection() && currentStep === 'collection-form') {
      setStep('source-select');
      return null;
    }

    switch (currentStep) {
      case 'collection-form':
        return <CollectionFormView humanReadableId={humanReadableId} />;
      case 'source-select':
        // Source select is rendered differently (full width)
        return null;
      case 'source-config':
        return <SourceConfigView
          humanReadableId={humanReadableId}
          isAddingToExisting={isAddingToExistingCollection()}
        />;
      case 'oauth-redirect':
        return <OAuthRedirectView />;
      case 'success':
        return <SuccessView
          onComplete={handleClose}
          isAddingToExisting={isAddingToExistingCollection()}
        />;
      default:
        return null;
    }
  };

  const isCreateDatabaseStep = currentStep === 'collection-form';

  // Determine if we should show the visualization.
  // The first create step stays intentionally minimal; later steps can use the preview rail.
  const showVisualization = !isCreateDatabaseStep &&
    currentStep !== 'source-select' &&
    currentStep !== 'oauth-redirect';

  // Determine column widths based on step
  const getColumnWidths = () => {
    // Use much wider form column for source-config (URL sharing needs more space)
    if (currentStep === 'source-config') {
      return { left: 'w-[640px]', right: 'flex-1' };
    }
    if (isCreateDatabaseStep) {
      return { left: 'w-full', right: 'hidden' };
    }
    return { left: 'w-[440px]', right: 'flex-1' };
  };

  const columnWidths = getColumnWidths();
  const modalSize = currentStep === 'source-config'
    ? 'w-[1440px] max-w-[95vw] h-[840px] max-h-[95vh]'
    : currentStep === 'source-select'
      ? 'w-[1240px] max-w-[95vw] h-[760px] max-h-[95vh]'
      : isCreateDatabaseStep
        ? 'w-[560px] max-w-[94vw] max-h-[92vh]'
        : 'w-[1120px] max-w-[94vw] h-[680px] max-h-[92vh]';
  const connectorLabel = sourceName || selectedSource || 'source';
  const dialogTitle = isAddingToExistingCollection()
    ? 'Add connector to context database'
    : selectedSource || flowType === 'create-with-source'
      ? `Connect ${connectorLabel}`
      : 'Create database workbench';
  const dialogDescription = isAddingToExistingCollection()
    ? 'Add a connector to an existing ContextD database'
    : selectedSource || flowType === 'create-with-source'
      ? `Create a ContextD database and configure the ${connectorLabel} connector`
      : 'Create a single-source context database workbench';

  return (
    <DialogPrimitive.Root
      open={isOpen}
      onOpenChange={(open) => {
        // Only handle close events, not open events
        if (!open && isOpen) {
          handleClose();
        }
      }}
    >
      <DialogPrimitive.Portal>
        {/* Custom overlay */}
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" />

        {/* Custom content without animations */}
        <DialogPrimitive.Content
          className={cn(
            "fixed left-[50%] top-[50%] z-50",
            "translate-x-[-50%] translate-y-[-50%]",
            modalSize,
            "rounded-lg shadow-2xl border overflow-hidden outline-none",
            "bg-card border-border"
          )}
          onPointerDownOutside={(e) => {
            // Prevent closing on outside click during OAuth
            if (currentStep === 'oauth-redirect') {
              e.preventDefault();
            }
          }}
          onEscapeKeyDown={(e) => {
            // Prevent escape key during OAuth
            if (currentStep === 'oauth-redirect') {
              e.preventDefault();
            }
          }}
        >
          {/* Hidden title and description for accessibility */}
          <VisuallyHidden.Root>
            <DialogPrimitive.Title>
              {dialogTitle}
            </DialogPrimitive.Title>
            <DialogPrimitive.Description>
              {dialogDescription}
            </DialogPrimitive.Description>
          </VisuallyHidden.Root>

          {/* Custom close button */}
          <button
            onClick={handleClose}
            className={cn(
              "absolute right-4 top-4 z-50 flex h-9 w-9 items-center justify-center rounded-md border border-border bg-card/95 text-muted-foreground shadow-sm backdrop-blur-sm transition-colors",
              "hover:bg-muted hover:text-foreground"
            )}
            aria-label="Close dialog"
          >
            <X className="h-4 w-4" />
          </button>

          {/* Layout with dynamic widths */}
          {currentStep === 'source-select' ? (
            // Full width for source select
            <SourceSelectView
              humanReadableId={humanReadableId}
              isAddingToExisting={isAddingToExistingCollection()}
            />
          ) : isCreateDatabaseStep ? (
            <div className="max-h-[92vh] overflow-hidden">
              {renderCurrentView()}
            </div>
          ) : (
            <div className="flex h-full">
              {/* Left column - Form */}
              <div className={cn(
                "border-r border-border bg-card transition-all duration-300",
                columnWidths.left
              )}>
                {renderCurrentView()}
              </div>

              {/* Right column - Visualization */}
              {showVisualization && (
                <div className={cn(
                  "overflow-auto bg-background transition-all duration-300",
                  columnWidths.right
                )}>
                  <CollectionVisualization
                    collectionName={isAddingToExistingCollection() ? existingCollectionName || collectionName : collectionName}
                    humanReadableId={humanReadableId}
                    selectedSource={selectedSource}
                    sourceName={sourceName}
                    sourceConnectionName={sourceConnectionName}
                    currentStep={currentStep}
                  />
                </div>
              )}
            </div>
          )}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
};
