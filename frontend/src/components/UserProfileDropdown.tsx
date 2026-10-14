import { useState, useEffect } from 'react';
import { useAuth } from '@/lib/auth-context';
import { useOrganizationStore } from '@/lib/stores/organizations';
import { Link, useNavigate } from 'react-router-dom';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger, DropdownMenuSub,
  DropdownMenuSubContent, DropdownMenuSubTrigger
} from '@/components/ui/dropdown-menu';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  ExternalLink, Building2, Settings,
  UserPlus, Crown, Shield, Users, Plus, LogOut, Check,
  CreditCard, Clock, Key, Sun, Moon, Monitor
} from 'lucide-react';
import { apiClient } from '@/lib/api';
import { cn } from '@/lib/utils';
import { useTheme } from '@/lib/theme-provider';
import { BillingInfo } from '@/types';

// Consistent styling for all menu items
const menuItemClass = "flex items-center gap-2 px-2 py-1.5 text-sm cursor-pointer";
const subMenuItemClass = "flex items-center gap-2 px-2 py-1.5 text-sm cursor-pointer";
const externalLinkClass = "flex items-center justify-between px-2 py-1.5 text-sm";

interface MenuItemWithIconProps {
  icon: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
  disabled?: boolean;
}

const MenuItemWithIcon = ({ icon, children, className, onClick, disabled }: MenuItemWithIconProps) => (
  <DropdownMenuItem
    onSelect={onClick}
    disabled={disabled}
    className={cn(
      menuItemClass, 
      "focus:bg-muted focus:text-foreground data-[highlighted]:bg-muted data-[highlighted]:text-foreground",
      className
    )}
  >
    <span className="w-4 h-4 flex items-center justify-center text-muted-foreground">
      {icon}
    </span>
    <span className="flex-1">{children}</span>
  </DropdownMenuItem>
);

const ExternalMenuLink = ({ href, children }: { href: string; children: React.ReactNode }) => (
  <DropdownMenuItem asChild>
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={externalLinkClass}
    >
      <span className="flex items-center gap-2">{children}</span>
      <ExternalLink className="h-3 w-3 opacity-40" />
    </a>
  </DropdownMenuItem>
);

const InternalMenuLink = ({ to, icon, children }: { to: string; icon: React.ReactNode; children: React.ReactNode }) => (
  <DropdownMenuItem asChild>
    <Link 
      to={to} 
      className={cn(
        menuItemClass,
        "focus:bg-muted focus:text-foreground data-[highlighted]:bg-muted data-[highlighted]:text-foreground"
      )}
    >
      <span className="w-4 h-4 flex items-center justify-center text-muted-foreground">
        {icon}
      </span>
      <span className="flex-1">{children}</span>
    </Link>
  </DropdownMenuItem>
);

// Consistent separator component
const MenuSeparator = () => <div className="h-px bg-border/10 my-1" />;

export function UserProfileDropdown({ collapsed = false }: { collapsed?: boolean } = {}) {
  const { user, logout } = useAuth();
  const { resolvedTheme, setTheme } = useTheme();
  const navigate = useNavigate();
  const isDark = resolvedTheme === 'dark';

  const {
    organizations,
    currentOrganization,
    fetchUserOrganizations,
    switchOrganization
  } = useOrganizationStore();

  const [firstName, setFirstName] = useState<string>('');
  const [isLoadingOrgs, setIsLoadingOrgs] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [billingInfo, setBillingInfo] = useState<BillingInfo | null>(null);
  const [isLoadingBilling, setIsLoadingBilling] = useState(false);

  useEffect(() => {
    if (user?.name) {
      const nameParts = user.name.split(' ');
      setFirstName(nameParts[0] || '');
    }
  }, [user]);

  // Fetch user organizations when component mounts or user changes
  useEffect(() => {
    const loadOrganizations = async () => {
      if (user) {
        try {
          setIsLoadingOrgs(true);
          await fetchUserOrganizations();
        } catch (error) {
          console.error('Failed to load organizations:', error);
        } finally {
          setIsLoadingOrgs(false);
        }
      }
    };

    loadOrganizations();
  }, [user, fetchUserOrganizations]);

  // Fetch billing info when organization changes
  useEffect(() => {
    const fetchBillingInfo = async () => {
      if (currentOrganization) {
        try {
          setIsLoadingBilling(true);
          const response = await apiClient.get('/billing/subscription');
          if (response.ok) {
            const data = await response.json();
            setBillingInfo(data);
          }
        } catch (error) {
          console.error('Failed to fetch billing info:', error);
          setBillingInfo(null);
        } finally {
          setIsLoadingBilling(false);
        }
      }
    };

    fetchBillingInfo();
  }, [currentOrganization]);

  // Refetch organizations when dropdown opens to ensure fresh data
  useEffect(() => {
    const refreshOrganizations = async () => {
      if (dropdownOpen && user) {
        try {
          setIsLoadingOrgs(true);
          // Always fetch fresh data when dropdown opens
          await fetchUserOrganizations();
        } catch (error) {
          console.error('Failed to refresh organizations:', error);
        } finally {
          setIsLoadingOrgs(false);
        }
      }
    };

    // Only refresh when dropdown opens (becomes true)
    if (dropdownOpen) {
      refreshOrganizations();
    }
  }, [dropdownOpen, user, fetchUserOrganizations]);

  const handleLogout = () => {
    setDropdownOpen(false);
    apiClient.clearToken();
    logout();
  };

  const handleSwitchOrganization = (orgId: string) => {
    // If clicking on the already selected organization, just close the dropdown
    if (orgId === currentOrganization?.id) {
      setDropdownOpen(false);
      return;
    }

    // Update the organization in the store first
    switchOrganization(orgId);
    setDropdownOpen(false);

    // Do a full page reload to ensure clean state
    window.location.href = '/';
  };

  const handleCreateOrganization = () => {
    setDropdownOpen(false);
    navigate('/onboarding');
  };

  const getRoleIcon = (role: string) => {
    switch (role) {
      case 'owner': return <Crown className="h-3 w-3 text-brand-lime/90" />;
      case 'admin': return <Shield className="h-3 w-3 text-brand-lime/90" />;
      default: return <Users className="h-3 w-3 text-brand-lime/90" />;
    }
  };

  const getPlanBadge = () => {
    if (!billingInfo || isLoadingBilling) return null;

    const planDisplayName = {
      developer: 'Developer',
      pro: 'Pro',
      team: 'Team',
      enterprise: 'Enterprise'
    }[billingInfo.plan] || billingInfo.plan;

    return (
      <Badge variant="secondary" className="text-xs px-1.5 py-0 h-5">
        {planDisplayName}
      </Badge>
    );
  };

  const closeDropdown = () => setDropdownOpen(false);

  return (
    <>
      <DropdownMenu open={dropdownOpen} onOpenChange={setDropdownOpen}>
        <DropdownMenuTrigger asChild>
          <button
            className={cn(
              "flex items-center rounded-lg text-sm transition-all bg-neutral-50/50 dark:bg-neutral-800/50 hover:bg-neutral-100/60 dark:hover:bg-neutral-700/50 focus:outline-none focus-visible:ring-1 focus-visible:ring-border active:bg-neutral-100/80 dark:active:bg-neutral-700/60",
              collapsed ? "h-8 w-8 justify-center p-0" : "w-full gap-3 px-3 py-2.5"
            )}
            aria-label={collapsed ? "User menu" : undefined}
          >
            <div
              className={cn(
                "rounded-full bg-muted/80 border border-border flex items-center justify-center text-foreground font-medium text-xs flex-shrink-0",
                collapsed ? "h-7 w-7" : "h-8 w-8"
              )}
            >
              {firstName
                ? firstName[0]
                : user?.email?.substring(0, 1).toUpperCase() || 'U'}
            </div>
            {!collapsed && (
              <div className="flex-1 text-left overflow-hidden min-w-0">
                <p className="font-medium text-sm text-foreground truncate">
                  {user?.name || "User"}
                </p>
                {currentOrganization && (
                  <p className="text-[10px] text-muted-foreground/70 truncate mt-0.5">
                    {currentOrganization.name}
                  </p>
                )}
              </div>
            )}
          </button>
        </DropdownMenuTrigger>

        <DropdownMenuContent
          className="w-56 bg-card border-border"
          align="start"
          side="top"
          sideOffset={8}
          onEscapeKeyDown={closeDropdown}
          onInteractOutside={closeDropdown}
        >
          {/* User Info Section */}
          <div className="px-2 py-1.5 border-b border-border/10 bg-muted/20">
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground font-medium truncate">
                {user?.email}
              </p>
              {getPlanBadge()}
            </div>
          </div>

          {/* Organization Switcher */}
          <DropdownMenuSub>
            <DropdownMenuSubTrigger className={cn(
              subMenuItemClass, 
              "px-2 py-1.5 cursor-pointer",
              "focus:bg-muted focus:text-foreground",
              "data-[highlighted]:bg-muted data-[highlighted]:text-foreground",
              "data-[state=open]:bg-muted data-[state=open]:text-foreground"
            )}>
              <span className="flex items-center gap-2">
                <Building2 className="h-4 w-4" />
                {currentOrganization?.name || 'Select Organization'}
              </span>
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="w-72 p-1 shadow-xs animate-none max-h-96 overflow-y-auto" alignOffset={-120}>
              {isLoadingOrgs ? (
                <DropdownMenuItem disabled className="px-2 py-1.5 text-sm text-muted-foreground">
                  Loading organizations...
                </DropdownMenuItem>
              ) : organizations.length > 0 ? (
                <>
                  {organizations.map((org) => {
                    const isSelected = org.id === currentOrganization?.id;

                    return (
                      <DropdownMenuItem
                        key={org.id}
                        onSelect={() => handleSwitchOrganization(org.id)}
                        className={cn(
                          "flex items-center justify-between px-2 py-2.5 rounded-md transition-colors cursor-pointer",
                          isSelected
                            ? "bg-muted/60 text-foreground cursor-default"
                            : ""
                        )}
                      >
                        <div className="flex items-center gap-2.5 min-w-0 flex-1">
                          <span className="w-4 h-4 flex items-center justify-center">
                            <Building2 className="h-4 w-4 text-muted-foreground/60" />
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span className="text-sm truncate font-medium">{org.name}</span>
                              {getRoleIcon(org.role)}
                            </div>
                            {org.is_primary && (
                              <div className="text-xs mt-0.5 text-brand-yellow">Primary organization</div>
                            )}
                          </div>
                        </div>
                        <div className="shrink-0 ml-2">
                          {isSelected && (
                            <Check className="h-4 w-4 text-muted-foreground/60" />
                          )}
                        </div>
                      </DropdownMenuItem>
                    );
                  })}

                  <MenuSeparator />

                  <MenuItemWithIcon
                    icon={<Plus className="h-4 w-4" />}
                    onClick={handleCreateOrganization}
                    className="text-primary data-[highlighted]:bg-transparent"
                  >
                    Create Organization
                  </MenuItemWithIcon>
                </>
              ) : (
                <>
                  <DropdownMenuItem disabled className="px-2 py-1.5 text-sm text-muted-foreground">
                    No organizations found
                  </DropdownMenuItem>

                  <MenuSeparator />

                  <MenuItemWithIcon
                    icon={<Plus className="h-4 w-4" />}
                    onClick={handleCreateOrganization}
                    className="text-primary data-[highlighted]:bg-transparent"
                  >
                    Create Organization
                  </MenuItemWithIcon>
                </>
              )}
            </DropdownMenuSubContent>
          </DropdownMenuSub>

          {/* Organization Management */}
          {currentOrganization && ['owner', 'admin'].includes(currentOrganization.role) && (
            <>
              <MenuSeparator />

              <InternalMenuLink
                to="/organization/settings?tab=members"
                icon={<UserPlus className="h-4 w-4" />}
              >
                Invite Members
              </InternalMenuLink>

              <InternalMenuLink
                to="/organization/settings"
                icon={<Settings className="h-4 w-4" />}
              >
                Organization Settings
              </InternalMenuLink>

              {/* Billing Link */}
              {billingInfo && !billingInfo.has_active_subscription && (
                <InternalMenuLink
                  to="/organization/settings?tab=billing"
                  icon={<CreditCard className="h-4 w-4" />}
                >
                  Complete Billing Setup
                </InternalMenuLink>
              )}
            </>
          )}

          <MenuSeparator />

          {/* API Keys & Auth Providers */}
          <InternalMenuLink
            to="/api-keys"
            icon={<Key className="h-4 w-4" />}
          >
            API Keys
          </InternalMenuLink>

          <InternalMenuLink
            to="/auth-providers"
            icon={<Shield className="h-4 w-4" />}
          >
            Auth Providers
          </InternalMenuLink>

          <MenuSeparator />

          {/* Theme Selection - Toggle Design */}
          <div className="px-2 py-2">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium text-muted-foreground/70">Theme</span>
            </div>
            <div className="flex items-center gap-0 p-1 bg-muted/50 rounded-lg">
              <button
                onClick={() => setTheme('light')}
                className={cn(
                  "flex-1 p-1.5 rounded-md transition-all duration-200 flex items-center justify-center",
                  resolvedTheme === 'light'
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
                title="Light mode"
              >
                <Sun className="w-4 h-4" />
              </button>
              <button
                onClick={() => setTheme('dark')}
                className={cn(
                  "flex-1 p-1.5 rounded-md transition-all duration-200 flex items-center justify-center",
                  resolvedTheme === 'dark'
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
                title="Dark mode"
              >
                <Moon className="w-4 h-4" />
              </button>
              <button
                onClick={() => setTheme('system')}
                className={cn(
                  "flex-1 p-1.5 rounded-md transition-all duration-200 flex items-center justify-center",
                  (resolvedTheme !== 'dark' && resolvedTheme !== 'light')
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
                title="System theme"
              >
                <Monitor className="w-4 h-4" />
              </button>
            </div>
          </div>

          <MenuSeparator />

          {/* Admin Section */}
          {user?.is_admin && (
            <>
              <InternalMenuLink
                to="/admin"
                icon={<Shield className="h-4 w-4" />}
              >
                Admin Dashboard
              </InternalMenuLink>

              <MenuSeparator />
            </>
          )}

          <MenuSeparator />

          {/* Logout */}
          <MenuItemWithIcon
            icon={<LogOut className="h-4 w-4" />}
            onClick={handleLogout}
            className="text-muted-foreground/80"
          >
            Sign out
          </MenuItemWithIcon>
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  );
}
