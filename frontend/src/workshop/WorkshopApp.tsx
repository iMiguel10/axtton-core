import { useQuery } from "@tanstack/react-query";
import {
  Building2,
  Car,
  ClipboardList,
  IdCard,
  LayoutDashboard,
  ScrollText,
  ShieldCheck,
  Store,
  Users,
  Wallet,
} from "lucide-react";
import { lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, Route, Routes } from "react-router-dom";

import { AppSplash, DetailSkeleton } from "@/shared/components/Loading";

import { ActiveWorkshopCards } from "./features/account/ActiveWorkshopCards";
import { AppLayout, type NavGroup } from "./features/layout/AppLayout";
import { CommandPalette } from "./features/layout/CommandPalette";
import { ConnectionNotice } from "./features/layout/ConnectionNotice";
import { fetchStaff } from "./features/orders/api";
import { ActiveWorkshopProvider, useActiveWorkshop } from "./features/session/ActiveWorkshop";
import { currentActor } from "./lib/session";

// Cada pantalla, en su propio trozo: se descarga al visitarla, no en la primera
// carga (que en el móvil del taller se notaba: un solo fichero de 700 kB). El
// marco (barra lateral, sesión, taller activo) sí va en el principal.
const AccountPage = lazy(() => import("./features/account/AccountPage").then((m) => ({ default: m.AccountPage })));
const AdminSuperadminsPage = lazy(() => import("./features/admin/AdminSuperadminsPage").then((m) => ({ default: m.AdminSuperadminsPage })));
const AdminWorkshopsPage = lazy(() => import("./features/admin/AdminWorkshopsPage").then((m) => ({ default: m.AdminWorkshopsPage })));
const AuditPage = lazy(() => import("./features/audit/AuditPage").then((m) => ({ default: m.AuditPage })));
const ForgotPasswordPage = lazy(() => import("./features/auth/ForgotPasswordPage").then((m) => ({ default: m.ForgotPasswordPage })));
const InvitationPage = lazy(() => import("./features/auth/InvitationPage").then((m) => ({ default: m.InvitationPage })));
const LoginPage = lazy(() => import("./features/auth/LoginPage").then((m) => ({ default: m.LoginPage })));
const ResetPasswordPage = lazy(() => import("./features/auth/ResetPasswordPage").then((m) => ({ default: m.ResetPasswordPage })));
const SuperadminInvitationPage = lazy(() => import("./features/auth/SuperadminInvitationPage").then((m) => ({ default: m.SuperadminInvitationPage })));
const ClientDetailPage = lazy(() => import("./features/clients/ClientDetailPage").then((m) => ({ default: m.ClientDetailPage })));
const ClientNewPage = lazy(() => import("./features/clients/ClientNewPage").then((m) => ({ default: m.ClientNewPage })));
const ClientsPage = lazy(() => import("./features/clients/ClientsPage").then((m) => ({ default: m.ClientsPage })));
const EmployeesPage = lazy(() => import("./features/employees/EmployeesPage").then((m) => ({ default: m.EmployeesPage })));
const HomePage = lazy(() => import("./features/home/HomePage").then((m) => ({ default: m.HomePage })));
const OrderDetailPage = lazy(() => import("./features/orders/OrderDetailPage").then((m) => ({ default: m.OrderDetailPage })));
const UnpaidOrdersPage = lazy(() => import("./features/orders/UnpaidOrdersPage").then((m) => ({ default: m.UnpaidOrdersPage })));
const OrderNewPage = lazy(() => import("./features/orders/OrderNewPage").then((m) => ({ default: m.OrderNewPage })));
const OrdersPage = lazy(() => import("./features/orders/OrdersPage").then((m) => ({ default: m.OrdersPage })));
const VehicleDetailPage = lazy(() => import("./features/vehicles/VehicleDetailPage").then((m) => ({ default: m.VehicleDetailPage })));
const VehicleNewPage = lazy(() => import("./features/vehicles/VehicleNewPage").then((m) => ({ default: m.VehicleNewPage })));
const SettingsPage = lazy(() => import("./features/settings/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const VehiclesPage = lazy(() => import("./features/vehicles/VehiclesPage").then((m) => ({ default: m.VehiclesPage })));

export function WorkshopApp() {
  return (
    <Suspense fallback={<AppSplash />}>
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/invitations/:workshopId/:token" element={<InvitationPage />} />
      <Route path="/superadmin-invitations/:token" element={<SuperadminInvitationPage />} />
      <Route path="*" element={<SessionGate />} />
    </Routes>
    </Suspense>
  );
}

/**
 * Decide qué aplicación enseñar según el actor de la sesión. Es solo navegación:
 * si alguien fuerza la otra, cada prefijo de la API lo rechaza igual (A5).
 */
function SessionGate() {
  const actor = useQuery({ queryKey: ["actor"], queryFn: currentActor, staleTime: Infinity });

  if (actor.isPending) return <AppSplash />;
  if (actor.data === null || actor.isError) return <Navigate to="/login" replace />;
  if (actor.data === "client") {
    window.location.assign("/portal");
    return null;
  }
  if (actor.data === "superadmin") return <SuperadminRoutes />;
  return (
    <ActiveWorkshopProvider>
      <StaffRoutes />
    </ActiveWorkshopProvider>
  );
}

function SuperadminRoutes() {
  const { t } = useTranslation();
  const groups: NavGroup[] = [
    {
      label: t("layout.platform"),
      items: [
        { to: "/admin", label: t("nav.workshops"), icon: Building2 },
        { to: "/admin/superadmins", label: t("nav.superadmins"), icon: ShieldCheck },
        { to: "/admin/audit", label: t("nav.audit"), icon: ScrollText },
      ],
    },
  ];
  return (
    <AppLayout
      groups={groups}
      user={{ name: t("layout.superadmin"), detail: t("layout.platform") }}
      accountPath="/admin/account"
    >
      <Suspense fallback={<DetailSkeleton />}>
      <Routes>
        <Route path="/admin" element={<AdminWorkshopsPage />} />
        <Route path="/admin/superadmins" element={<AdminSuperadminsPage />} />
        <Route path="/admin/audit" element={<AuditPage scope={{ prefix: "/admin" }} />} />
        <Route path="/admin/account" element={<AccountPage prefix="/admin" />} />
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Routes>
      </Suspense>
    </AppLayout>
  );
}

function StaffRoutes() {
  const { t } = useTranslation();
  const {
    workshopId,
    employeeId,
    role,
    canManageEmployees,
    canViewAudit,
    canManageClients,
    canManageOrders,
    canManageSettings,
  } = useActiveWorkshop();
  const groups: NavGroup[] = [
    {
      label: t("layout.workshop"),
      items: [
        { to: "/", label: t("nav.home"), icon: LayoutDashboard },
        { to: "/orders", label: t("nav.orders"), icon: ClipboardList },
        { to: "/orders/unpaid", label: t("nav.unpaid"), icon: Wallet },
        { to: "/clients", label: t("nav.clients"), icon: Users },
        { to: "/vehicles", label: t("nav.vehicles"), icon: Car },
      ],
    },
    ...(canManageEmployees || canViewAudit || canManageSettings
      ? [
          {
            label: t("layout.management"),
            items: [
              ...(canManageSettings ? [{ to: "/settings", label: t("nav.settings"), icon: Store }] : []),
              ...(canManageEmployees
                ? [{ to: "/employees", label: t("nav.employees"), icon: IdCard }]
                : []),
              ...(canViewAudit ? [{ to: "/audit", label: t("nav.audit"), icon: ScrollText }] : []),
            ],
          },
        ]
      : []),
  ];
  // El nombre de mi ficha sale del directorio del personal, que ya se pide para
  // anotar trabajos: la sesión no lleva el nombre.
  const staff = useQuery({
    queryKey: ["staff", workshopId],
    queryFn: () => fetchStaff(workshopId),
    staleTime: 60_000,
  });
  const me = staff.data?.find((member) => member.id === employeeId);
  return (
    <AppLayout
      groups={groups}
      user={{ name: me?.name ?? "", detail: t(`roles.${role}`) }}
      accountPath="/account"
      workshopSwitcher
      quickAction={canManageOrders ? { to: "/orders/new", label: t("orders.new") } : undefined}
      search={
        <CommandPalette
          groups={groups}
          actions={[
            ...(canManageOrders ? [{ to: "/orders/new", label: t("orders.new") }] : []),
            ...(canManageClients
              ? [
                  { to: "/clients/new", label: t("clients.new") },
                  { to: "/vehicles/new", label: t("vehicles.new") },
                ]
              : []),
            { to: "/account", label: t("nav.account") },
          ]}
        />
      }
      notice={<ConnectionNotice />}
    >
      <Suspense fallback={<DetailSkeleton />}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/orders" element={<OrdersPage />} />
        {canManageOrders && <Route path="/orders/new" element={<OrderNewPage />} />}
        <Route path="/orders/unpaid" element={<UnpaidOrdersPage />} />
        <Route path="/orders/:orderId" element={<OrderDetailPage />} />
        <Route path="/clients" element={<ClientsPage />} />
        {canManageClients && <Route path="/clients/new" element={<ClientNewPage />} />}
        <Route path="/clients/:clientId" element={<ClientDetailPage />} />
        <Route path="/vehicles" element={<VehiclesPage />} />
        {canManageClients && <Route path="/vehicles/new" element={<VehicleNewPage />} />}
        <Route path="/vehicles/:vehicleId" element={<VehicleDetailPage />} />
        {canManageSettings && <Route path="/settings" element={<SettingsPage />} />}
        {canManageEmployees && <Route path="/employees" element={<EmployeesPage />} />}
        {canViewAudit && (
          <Route
            path="/audit"
            element={<AuditPage scope={{ prefix: "/workshop", workshopId }} />}
          />
        )}
        <Route path="/account" element={<AccountPage prefix="/workshop" aside={<ActiveWorkshopCards />} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </Suspense>
    </AppLayout>
  );
}
