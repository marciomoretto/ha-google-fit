"""Support for Google Fit."""
from __future__ import annotations

from aiohttp.client_exceptions import ClientError, ClientResponseError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import (
    OAuth2Session,
    async_get_config_entry_implementation,
)

from .coordinator import Coordinator

from .api import AsyncConfigEntryAuth, LOGGER
from .const import DOMAIN

PLATFORM = Platform.SENSOR


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Google Fit from a config entry."""
    LOGGER.debug(
        "Setting up Google Fit integration from configuration %s", entry.entry_id
    )
    implementation = await async_get_config_entry_implementation(hass, entry)

    LOGGER.debug("Attempting to create OAuth2 session")
    session = OAuth2Session(hass, entry, implementation)
    auth = AsyncConfigEntryAuth(hass, async_get_clientsession(hass), session)
    try:
        LOGGER.debug("Checking OAuth2 session is valid.")
        await auth.check_and_refresh_token()
    except ClientResponseError as err:
        if 400 <= err.status < 500:
            raise ConfigEntryAuthFailed(
                "OAuth session is not valid, re-authentication required"
            ) from err
        raise ConfigEntryNotReady from err
    except ClientError as err:
        raise ConfigEntryNotReady from err

    LOGGER.debug("Creating Google Fit data access coordinator.")
    coordinator = Coordinator(hass=hass, config=entry, auth=auth)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "auth": auth,
        "coordinator": coordinator,
    }

    # Registrar o serviço para patch de dados de hidratação
    async def hydration_data_service(call) -> None:
        """Service to patch hydration data."""
        coordinator = Coordinator(hass=hass, config=entry, auth=auth)
        volume = call.data.get("volume")
        await coordinator.patch_hydration_data(volume)

    hass.services.async_register(
        DOMAIN, 'hydration_data', hydration_data_service
    )


    # Criação do DataSource
    data_source_id = await auth.create_data_source()
    hass.data[DOMAIN][entry.entry_id]['data_source_id'] = data_source_id

    await hass.config_entries.async_forward_entry_setup(entry, PLATFORM)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    # Attempt to retrieve values immediately, not waiting for first
    # time interval to pass
    LOGGER.debug("Requesting initial sensor value fetch.")
    await coordinator.async_config_entry_first_refresh()

    LOGGER.debug("Integration setup successful.")
    return True


async def update_listener(hass, entry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, [PLATFORM]):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
