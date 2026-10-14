// Simple event bus for collection-related events
export const COLLECTION_DELETED = 'collection:deleted';
export const COLLECTION_CREATED = 'collection:created';
export const COLLECTION_UPDATED = 'collection:updated';
export const SOURCE_CONNECTION_UPDATED = 'source_connection:updated';

/**
 * Emit a collection event
 * @param eventName The name of the event
 * @param data Optional data to include with the event
 */
export const emitCollectionEvent = (eventName: string, data?: any) => {
  const event = new CustomEvent(eventName, { detail: data });
  window.dispatchEvent(event);
};

/**
 * Subscribe to a collection event
 * @param eventName The name of the event to listen for
 * @param callback The callback to execute when the event is fired
 * @returns A cleanup function to remove the event listener
 */
export const onCollectionEvent = (eventName: string, callback: (data?: any) => void) => {
  const handler = (event: CustomEvent) => callback(event.detail);
  window.addEventListener(eventName, handler as EventListener);

  // Return cleanup function
  return () => window.removeEventListener(eventName, handler as EventListener);
};
