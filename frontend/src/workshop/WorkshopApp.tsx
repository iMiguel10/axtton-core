import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Navigate, Route, Routes } from "react-router-dom";

import { AccountPage } from "./features/account/AccountPage";
import { AdminSuperadminsPage } from "./features/admin/AdminSuperadminsPage";
import { AdminWorkshopsPage } from "./features/admin/AdminWorkshopsPage";
import { AuditPage } from "./features/audit/AuditPage";
import { ForgotPasswordPage } from "./features/auth/ForgotPasswordPage";
import { InvitationPage } from "./features/auth/InvitationPage";
import { LoginPage } from "./features/auth/LoginPage";
import { ResetPasswordPage } from "./features/auth/ResetPasswordPage";
import { SuperadminInvitationPage } from "./features/auth/SuperadminInvitationPage";
import { ClientDetailPage } from "./features/clients/ClientDetailPage";
import { ClientNewPage } from "./features/clients/ClientNewPage";
import { ClientsPage } from "./features/clients/ClientsPage";
import { EmployeesPage } from "./features/employees/EmployeesPage";
import { HomePage } from "./features/home/HomePage";
import { AppLayout } from "./features/layout/AppLayout";
import { ActiveWorkshopProvider, useActiveWorkshop } from "./features/session/ActiveWorkshop";
import { currentActor } from "./lib/session";

export function WorkshopApp() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/invitations/:workshopId/:token" element={<InvitationPage />} />
      <Route path="/superadmin-invitations/:token" element={<SuperadminInvitationPage />} />
      <Route path="*" element={<SessionGate />} />
    </Routes>
  );
}

/**
 * Decide qué aplicación enseñar según el actor de la sesión. Es solo navegación:
 * si alguien fuerza la otra, cada prefijo de la API lo rechaza igual (A5).
 */
function SessionGate() {
  const { t } = useTranslation();
  const actor = useQuery({ queryKey: ["actor"], queryFn: currentActor, staleTime: Infinity });

  if (actor.isPending) return <p className="p-6">{t("common.loading")}</p>;
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
  const nav = [
    { to: "/admin", label: t("nav.workshops") },
    { to: "/admin/superadmins", label: t("nav.superadmins") },
    { to: "/admin/audit", label: t("nav.audit") },
    { to: "/admin/account", label: t("nav.account") },
  ];
  return (
    <AppLayout nav={nav}>
      <Routes>
        <Route path="/admin" element={<AdminWorkshopsPage />} />
        <Route path="/admin/superadmins" element={<AdminSuperadminsPage />} />
        <Route path="/admin/audit" element={<AuditPage scope={{ prefix: "/admin" }} />} />
        <Route path="/admin/account" element={<AccountPage prefix="/admin" />} />
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Routes>
    </AppLayout>
  );
}

function StaffRoutes() {
  const { t } = useTranslation();
  const { workshopId, canManageEmployees, canViewAudit, canManageClients } = useActiveWorkshop();
  const nav = [
    { to: "/", label: t("nav.home") },
    { to: "/clients", label: t("nav.clients") },
    ...(canManageEmployees ? [{ to: "/employees", label: t("nav.employees") }] : []),
    ...(canViewAudit ? [{ to: "/audit", label: t("nav.audit") }] : []),
    { to: "/account", label: t("nav.account") },
  ];
  return (
    <AppLayout nav={nav} workshopSwitcher>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/clients" element={<ClientsPage />} />
        {canManageClients && <Route path="/clients/new" element={<ClientNewPage />} />}
        <Route path="/clients/:clientId" element={<ClientDetailPage />} />
        {canManageEmployees && <Route path="/employees" element={<EmployeesPage />} />}
        {canViewAudit && (
          <Route
            path="/audit"
            element={<AuditPage scope={{ prefix: "/workshop", workshopId }} />}
          />
        )}
        <Route path="/account" element={<AccountPage prefix="/workshop" />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppLayout>
  );
}
