import { apiClient, ensureOk } from "@/lib/api";
import { redirectWithError } from "@/lib/error-utils";
import { useNavigate } from "react-router-dom";

// Function for OAuth2 authentication flow
const create_credentials_oauth = async (
    dialogState: Record<string, any>,
    navigate?: any  // Accept navigate as a parameter
): Promise<boolean> => {
    try {
        const { sourceDetails, sourceShortName } = dialogState;
        // Don't destructure authValues - access it directly to ensure we get the correct object
        const authValues = dialogState.authValues;

        // Make sure we're including dialogId in the stored state
        const stateToStore = {
            ...dialogState,
            // If dialogId isn't already set, use a default one
            dialogId: dialogState.dialogId || "default"
        };

        // Save state to sessionStorage (persists only for this tab, cleared on tab close)
        sessionStorage.setItem('oauth_dialog_state', JSON.stringify(stateToStore));

        // Check if we have a client_id in auth fields
        let url = `/source-connections/${sourceShortName}/oauth2_url`;

        // If client_id is present in auth values, add it as a query parameter
        if (authValues && authValues.client_id) {
            url += `?client_id=${encodeURIComponent(authValues.client_id)}`;
        }

        // Get OAuth URL from backend
        const response = await apiClient.get(url);

        await ensureOk(response, `Failed to start OAuth authentication for ${sourceDetails?.name || sourceShortName}`);

        const data = await response.json();

        // Backend returns the URL in the 'url' field
        const authorizationUrl = data.url;

        if (!authorizationUrl) {
            throw new Error("No authorization URL returned from server");
        }

        // Redirect to OAuth provider
        window.location.href = authorizationUrl;

        // Return value doesn't matter as we're redirecting away
        return true;
    } catch (error) {
        // Replace the alert with redirectWithError
        if (navigate) {
            // If navigate is available, use it for redirection
            redirectWithError(navigate, {
                serviceName: dialogState.sourceDetails?.name || dialogState.sourceShortName,
                sourceShortName: dialogState.sourceShortName,
                errorMessage: error instanceof Error ? error.message : String(error),
                dialogId: dialogState.dialogId,
                canRetry: true,
                dialogState: dialogState,
                timestamp: Date.now()
            }, dialogState.sourceDetails?.name || dialogState.sourceShortName);
        } else {
            // Fallback to window.location if navigate isn't available
            redirectWithError(window.location, {
                serviceName: dialogState.sourceDetails?.name || dialogState.sourceShortName,
                sourceShortName: dialogState.sourceShortName,
                errorMessage: error instanceof Error ? error.message : String(error),
                dialogId: dialogState.dialogId,
                canRetry: true,
                dialogState: dialogState,
                timestamp: Date.now()
            }, dialogState.sourceDetails?.name || dialogState.sourceShortName);
        }
        return false;
    }
};

// Function for non-OAuth authentication flow that calls the backend API
const create_credential_non_oauth = async (
    authValues: Record<string, any>,
    sourceDetails: any,
    sourceShortName: string,
    navigate?: any,
    dialogState?: Record<string, any>  // Add this parameter
): Promise<{ success: boolean, credentialId?: string }> => {
    try {
        // Prepare the credential data according to IntegrationCredentialRawCreate schema
        const credentialData = {
            name: `${sourceDetails.name} Credential`,
            integration_short_name: sourceShortName,
            description: `Credential for ${sourceDetails.name}`,
            integration_type: "source", // Must be uppercase to match the enum
            auth_type: sourceDetails.auth_type,
            auth_config_class: sourceDetails.auth_config_class,
            auth_fields: authValues // The auth values from the form
        };

        // Use /connections/credentials/ as the base path
        const response = await apiClient.post(
            `/connections/credentials/source/${sourceShortName}`,
            credentialData
        );

        await ensureOk(response, `Failed to authenticate with ${sourceDetails.name}`);

        // Get the created credential with its ID
        const credential = await response.json();

        // Return success with credential ID instead of showing alert
        return { success: true, credentialId: credential.id };
    } catch (error) {
        // Replace the alert with redirectWithError
        if (navigate) {
            redirectWithError(navigate, {
                serviceName: sourceDetails?.name || sourceShortName,
                sourceShortName: sourceShortName,
                errorMessage: error instanceof Error ? error.message : String(error),
                dialogId: dialogState?.dialogId,
                canRetry: true,
                dialogState: dialogState,
                timestamp: Date.now()
            }, sourceDetails?.name || sourceShortName);
        } else {
            redirectWithError(window.location, {
                serviceName: sourceDetails?.name || sourceShortName,
                sourceShortName: sourceShortName,
                errorMessage: error instanceof Error ? error.message : String(error),
                dialogId: dialogState?.dialogId,
                canRetry: true,
                dialogState: dialogState,
                timestamp: Date.now()
            }, sourceDetails?.name || sourceShortName);
        }
        return { success: false };
    }
};

// Update authenticateSource to handle the credential ID
export const authenticateSource = async (
    dialogState: Record<string, any>,
    navigate?: any
): Promise<{ success: boolean, credentialId?: string }> => {
    const { authValues, sourceDetails, sourceShortName } = dialogState;

    try {
        // Check auth_type and call appropriate function
        if (sourceDetails.auth_type && sourceDetails.auth_type.startsWith('oauth2')) {
            return { success: await create_credentials_oauth(dialogState, navigate) };
        } else {
            return await create_credential_non_oauth(authValues, sourceDetails, sourceShortName, navigate, dialogState);
        }
    } catch (error) {
        // Add redirect here too for any uncaught errors
        if (navigate) {
            redirectWithError(navigate, {
                serviceName: dialogState.sourceDetails?.name || dialogState.sourceShortName,
                sourceShortName: dialogState.sourceShortName,
                errorMessage: error instanceof Error ? error.message : String(error),
                dialogId: dialogState.dialogId,
                canRetry: true,
                dialogState: dialogState,
                timestamp: Date.now()
            }, dialogState.sourceDetails?.name || dialogState.sourceShortName);
        } else {
            redirectWithError(window.location, {
                serviceName: dialogState.sourceDetails?.name || dialogState.sourceShortName,
                sourceShortName: dialogState.sourceShortName,
                errorMessage: error instanceof Error ? error.message : String(error),
                dialogId: dialogState.dialogId,
                canRetry: true,
                dialogState: dialogState,
                timestamp: Date.now()
            }, dialogState.sourceDetails?.name || dialogState.sourceShortName);
        }
        return { success: false };
    }
};

export default authenticateSource;
