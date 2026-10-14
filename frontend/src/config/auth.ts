// Authentication configuration

// First check runtime config (from window.ENV), then development env vars, then default values

// Whether authentication is entirely disabled (for testing)
const disableAuth = (window.ENV?.DISABLE_AUTH === true) ||
  (import.meta.env.VITE_DISABLE_AUTH === 'true') ||
  false;

// Whether authentication is enabled (Auth0)
const authEnabled = disableAuth
  ? false
  : (window.ENV?.AUTH_ENABLED !== undefined)
    ? window.ENV.AUTH_ENABLED
    : (import.meta.env.VITE_ENABLE_AUTH === 'true') || false;

const config = {
  authDisabled: disableAuth,
  authEnabled,

  // Dev auth is automatically enabled when Auth0 is disabled, unless auth is
  // intentionally bypassed for local system-user mode.
  devAuthEnabled: !disableAuth && !authEnabled,

  // Auth0 configuration
  auth0: {
    domain: window.ENV?.AUTH0_DOMAIN ||
      import.meta.env.VITE_AUTH0_DOMAIN ||
      '',
    clientId: window.ENV?.AUTH0_CLIENT_ID ||
      import.meta.env.VITE_AUTH0_CLIENT_ID ||
      '',
    audience: window.ENV?.AUTH0_AUDIENCE ||
      import.meta.env.VITE_AUTH0_AUDIENCE ||
      ''
  },

  // Whether all auth configuration is valid
  isConfigValid: function() {
    if (this.authDisabled) return true; // Auth bypassed entirely
    if (this.devAuthEnabled) return true; // Dev auth doesn't need Auth0 config

    return Boolean(
      this.auth0.domain &&
      this.auth0.clientId &&
      this.auth0.audience
    );
  }
};

export default config;
