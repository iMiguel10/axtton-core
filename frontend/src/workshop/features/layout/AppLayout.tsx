import { Building2, ChevronsUpDown, Languages, LogOut, Moon, Sun, UserRound, type LucideIcon } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation } from "react-router-dom";

import { Brand, BrandMark } from "@/shared/components/Brand";
import { useTheme } from "@/shared/components/Preferences";
import { Avatar, AvatarFallback } from "@/shared/components/ui/avatar";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/shared/components/ui/breadcrumb";
import { buttonVariants } from "@/shared/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/shared/components/ui/dropdown-menu";
import { Separator } from "@/shared/components/ui/separator";
import { APP_COMMIT, APP_VERSION, versionLabel } from "@/shared/lib/version";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from "@/shared/components/ui/sidebar";

import { signOut } from "../../lib/session";
import { NewVersionNotice } from "./NewVersionNotice";
import { PageCrumbProvider, useCurrentCrumb } from "./PageCrumb";
import { useActiveWorkshop } from "../session/ActiveWorkshop";

export type NavItem = { to: string; label: string; icon: LucideIcon };
export type NavGroup = { label: string; items: NavItem[] };

/**
 * El apartado en el que estoy: el de la ruta más larga que la contiene. Así
 * "Clientes" sigue marcado en la ficha de un cliente, y en `/orders/unpaid` se
 * marca "Pendientes de cobro" y no "Órdenes". El inicio, solo exacto.
 */
function activeItem(pathname: string, groups: NavGroup[]): NavItem | undefined {
  return groups
    .flatMap((group) => group.items)
    .filter((item) => pathname === item.to || (item.to !== "/" && pathname.startsWith(`${item.to}/`)))
    .sort((a, b) => b.to.length - a.to.length)[0];
}

/**
 * La estructura de la aplicación (como el bloque dashboard-01 de shadcn): barra
 * lateral con la marca, el taller, los apartados y la cuenta; cabecera con el
 * título del apartado y la acción rápida; y el contenido. En el móvil, la barra
 * es un panel que se abre desde la cabecera.
 */
export function AppLayout({
  groups,
  user,
  accountPath,
  workshopSwitcher = false,
  quickAction,
  search,
  notice,
  children,
}: {
  groups: NavGroup[];
  /** Quién ha entrado: su nombre y, debajo, su rol. */
  user: { name: string; detail: string };
  accountPath: string;
  /** Solo para el personal: el superadministrador no tiene taller activo. */
  workshopSwitcher?: boolean;
  /** El botón de la cabecera, para lo que más se hace (abrir una orden). */
  quickAction?: { to: string; label: string };
  /** La búsqueda global de la cabecera (Ctrl+K), para el personal. */
  search?: ReactNode;
  /** Bajo la cabecera, en todas las pantallas (la conexión, para el personal). */
  notice?: ReactNode;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const current = activeItem(pathname, groups);
  // Mi cuenta no está en la barra (está en el menú de la cuenta), pero tiene título.
  const title = current?.label ?? (pathname.startsWith(accountPath) ? t("nav.account") : undefined);
  return (
    <PageCrumbProvider>
    {/* Para el teclado: saltar la barra lateral y la cabecera de un Tab. Solo se
        ve al recibir el foco. */}
    <a
      href="#contenido"
      className="bg-background ring-ring sr-only z-50 rounded-md px-3 py-2 text-sm font-medium focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:ring-2"
    >
      {t("layout.skipToContent")}
    </a>
    <SidebarProvider
      style={
        {
          "--sidebar-width": "calc(var(--spacing) * 64)",
          "--header-height": "calc(var(--spacing) * 14)",
        } as CSSProperties
      }
    >
      <AppSidebar groups={groups} current={current} user={user} accountPath={accountPath} workshopSwitcher={workshopSwitcher} />
      <SidebarInset>
        <header className="bg-background/95 sticky top-0 z-20 flex h-(--header-height) shrink-0 items-center gap-2 border-b px-4 backdrop-blur lg:px-6">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="mx-1 data-vertical:h-4 data-vertical:self-center" />
          <HeaderCrumbs section={current} title={title} />
          <div className="ml-auto flex shrink-0 items-center gap-2">
            {search}
            {quickAction && (
              <Link to={quickAction.to} className={buttonVariants({ size: "sm" })}>
                {quickAction.label}
              </Link>
            )}
          </div>
        </header>
        <NewVersionNotice />
        {notice}
        {/* Marca de agua: el símbolo, grande y casi transparente, detrás de las
            tarjetas (que son opacas: solo se ve en los huecos). Decoración pura:
            ni recibe clics ni la leen los lectores de pantalla. Cuando cada taller
            tenga su logo (RF-02, F3), podría ser el suyo. */}
        <div aria-hidden className="pointer-events-none fixed -right-24 -bottom-24 z-0 opacity-[0.04] dark:opacity-[0.06]">
          <BrandMark className="h-[30rem]" />
        </div>
        <main id="contenido" tabIndex={-1} className="relative z-10 w-full flex-1 p-4 outline-none md:p-6">
          {children}
        </main>
      </SidebarInset>
    </SidebarProvider>
    </PageCrumbProvider>
  );
}

function AppSidebar({
  groups,
  current,
  user,
  accountPath,
  workshopSwitcher,
}: {
  groups: NavGroup[];
  current: NavItem | undefined;
  user: { name: string; detail: string };
  accountPath: string;
  workshopSwitcher: boolean;
}) {
  const { isMobile, setOpenMobile } = useSidebar();
  // En el móvil la barra es un panel encima del contenido: al elegir, se cierra.
  const close = () => {
    if (isMobile) setOpenMobile(false);
  };
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              size="lg"
              className="justify-center hover:bg-transparent active:bg-transparent"
              render={<Link to="/" onClick={close} />}
            >
              {/* Abierta, el logotipo entero; plegada, solo el símbolo. */}
              <Brand tone="onDark" className="h-11 group-data-[collapsible=icon]:hidden" />
              <BrandMark tone="onDark" className="hidden h-5 group-data-[collapsible=icon]:block" />
            </SidebarMenuButton>
          </SidebarMenuItem>
          {workshopSwitcher && <WorkshopSwitcher />}
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        {groups.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarMenu>
              {group.items.map((item) => (
                <SidebarMenuItem key={item.to}>
                  <SidebarMenuButton
                    isActive={item === current}
                    tooltip={item.label}
                    // aria-current a mano: NavLink solo marca la ruta exacta, y "Clientes"
                    // también es la página actual dentro de la ficha de un cliente.
                    render={<Link to={item.to} onClick={close} aria-current={item === current ? "page" : undefined} />}
                    className="data-active:text-sidebar-primary"
                  >
                    <item.icon />
                    <span>{item.label}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <UserMenu user={user} accountPath={accountPath} onNavigate={close} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase())
    .join("");
}

/** La cuenta: mi cuenta, idioma, tema y salir (antes, en la cabecera). */
function UserMenu({
  user,
  accountPath,
  onNavigate,
}: {
  user: { name: string; detail: string };
  accountPath: string;
  onNavigate: () => void;
}) {
  const { t, i18n } = useTranslation();
  const { isMobile } = useSidebar();
  const { dark, toggle } = useTheme();
  const nextLanguage = i18n.resolvedLanguage === "es" ? "en" : "es";
  const person = (
    <>
      <Avatar className="size-8 rounded-lg">
        <AvatarFallback className="bg-sidebar-accent text-sidebar-accent-foreground rounded-lg">
          {initials(user.name) || <UserRound />}
        </AvatarFallback>
      </Avatar>
      <span className="grid flex-1 text-left text-sm leading-tight">
        <span className="truncate font-medium">{user.name}</span>
        <span className="text-muted-foreground truncate text-xs">{user.detail}</span>
      </span>
    </>
  );
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <SidebarMenuButton
                size="lg"
                aria-label={t("layout.userMenu")}
                className="data-popup-open:bg-sidebar-accent data-popup-open:text-sidebar-accent-foreground"
              />
            }
          >
            {person}
            <ChevronsUpDown className="ml-auto size-4 group-data-[collapsible=icon]:hidden" />
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="min-w-56 rounded-lg"
            side={isMobile ? "bottom" : "right"}
            align="end"
            sideOffset={4}
          >
            <DropdownMenuGroup>
              <DropdownMenuLabel className="flex items-center gap-2 p-1 font-normal">{person}</DropdownMenuLabel>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem render={<Link to={accountPath} onClick={onNavigate} />}>
                <UserRound />
                {t("nav.account")}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => void i18n.changeLanguage(nextLanguage)}>
                <Languages />
                {t("layout.language", { language: nextLanguage.toUpperCase() })}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={toggle}>
                {dark ? <Sun /> : <Moon />}
                {t(dark ? "layout.lightTheme" : "layout.darkTheme")}
              </DropdownMenuItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => void signOut()}>
              <LogOut />
              {t("nav.signOut")}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {/* Discreta: para decirla al avisar de un fallo. La de la API, en Mi cuenta. */}
            <DropdownMenuGroup>
              <DropdownMenuLabel className="text-muted-foreground px-2 py-1 text-xs font-normal tabular-nums">
                {t("version.label", { version: versionLabel(APP_VERSION, APP_COMMIT) })}
              </DropdownMenuLabel>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}

/** El taller activo (RF-08), bajo la marca. Con uno solo, no hay nada que elegir. */
function WorkshopSwitcher() {
  const { t } = useTranslation();
  const { isMobile } = useSidebar();
  const { workshopId, workshopName, workshops, select } = useActiveWorkshop();
  const label = (
    <>
      <span className="bg-sidebar-accent text-sidebar-accent-foreground flex size-8 shrink-0 items-center justify-center rounded-lg">
        <Building2 className="size-4" />
      </span>
      <span className="grid flex-1 text-left text-sm leading-tight">
        <span className="text-muted-foreground text-xs">{t("workshop.active")}</span>
        <span className="truncate font-medium">{workshopName}</span>
      </span>
    </>
  );
  // Siempre un botón de la barra: plegada, se queda en el icono y el nombre sale
  // en el tooltip. Con un solo taller no abre nada.
  if (workshops.length === 1) {
    return (
      <SidebarMenuItem>
        <SidebarMenuButton
          size="lg"
          tooltip={workshopName}
          render={<div />}
          className="hover:bg-transparent hover:text-sidebar-foreground active:bg-transparent"
        >
          {label}
        </SidebarMenuButton>
      </SidebarMenuItem>
    );
  }
  return (
    <SidebarMenuItem>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <SidebarMenuButton
              size="lg"
              tooltip={workshopName}
              className="data-popup-open:bg-sidebar-accent data-popup-open:text-sidebar-accent-foreground"
            />
          }
        >
          {label}
          <ChevronsUpDown className="ml-auto size-4 group-data-[collapsible=icon]:hidden" />
        </DropdownMenuTrigger>
        <DropdownMenuContent className="min-w-56 rounded-lg" side={isMobile ? "bottom" : "right"} align="start" sideOffset={4}>
          <DropdownMenuGroup>
            <DropdownMenuLabel className="text-muted-foreground text-xs">{t("workshop.active")}</DropdownMenuLabel>
            {workshops.map((w) => (
              <DropdownMenuItem key={w.workshop_id} onClick={() => select(w.workshop_id)}>
                <Building2 />
                <span className={w.workshop_id === workshopId ? "font-medium" : undefined}>{w.workshop_name}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </SidebarMenuItem>
  );
}

/**
 * El título de la cabecera, como migas de pan: el apartado y, si la página lo
 * dice, dónde estoy dentro (`usePageCrumb`). Sin miga, el apartado es el título
 * de la página (`h1`): los listados no repiten el suyo dentro. Con miga, el
 * apartado es un enlace para volver, y la página lleva su propio `h1`.
 */
function HeaderCrumbs({ section, title }: { section: NavItem | undefined; title: string | undefined }) {
  const crumb = useCurrentCrumb();
  if (!crumb || !section) {
    return <h1 className="truncate text-base font-medium">{title}</h1>;
  }
  return (
    <Breadcrumb className="min-w-0">
      <BreadcrumbList className="flex-nowrap">
        <BreadcrumbItem>
          <BreadcrumbLink render={<Link to={section.to} />}>{section.label}</BreadcrumbLink>
        </BreadcrumbItem>
        <BreadcrumbSeparator />
        <BreadcrumbItem className="min-w-0">
          <BreadcrumbPage className="truncate font-medium">
            {crumb.asTitle ? <h1 className="inline">{crumb.label}</h1> : crumb.label}
          </BreadcrumbPage>
        </BreadcrumbItem>
      </BreadcrumbList>
    </Breadcrumb>
  );
}
