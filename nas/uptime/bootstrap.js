"use strict";

const fs = require("node:fs");
const { io } = require("socket.io-client");

const baseUrl = process.env.UPTIME_KUMA_BOOTSTRAP_URL || "http://127.0.0.1:3001";
const configPath = process.env.UPTIME_KUMA_BOOTSTRAP_CONFIG || "/bootstrap-config.json";
const secretsDir = process.env.UPTIME_KUMA_BOOTSTRAP_SECRETS || "/run/uptime-kuma-secrets";
const passwordPath = `${secretsDir}/admin-password`;
const usernamePath = `${secretsDir}/admin-username`;

function readRequiredFile(path) {
    const value = fs.readFileSync(path, "utf8").trim();
    if (!value) {
        throw new Error(`Empty value in ${path}`);
    }
    return value;
}

function readOptionalFile(path, fallback) {
    if (!fs.existsSync(path)) {
        return fallback;
    }
    const value = fs.readFileSync(path, "utf8").trim();
    return value || fallback;
}

function waitForEvent(socket, event, timeoutMs) {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
            socket.off(event, onEvent);
            reject(new Error(`${event} timed out after ${timeoutMs}ms`));
        }, timeoutMs);

        function onEvent(payload) {
            clearTimeout(timer);
            resolve(payload);
        }

        socket.once(event, onEvent);
    });
}

function connectSocket(url) {
    return new Promise((resolve, reject) => {
        const socket = io(url, {
            reconnection: false,
            timeout: 10000,
            transports: ["websocket"],
        });

        const timer = setTimeout(() => {
            socket.close();
            reject(new Error(`Failed to connect to ${url}`));
        }, 10000);

        socket.once("connect", () => {
            clearTimeout(timer);
            resolve(socket);
        });

        socket.once("connect_error", (error) => {
            clearTimeout(timer);
            socket.close();
            reject(error);
        });
    });
}

function emitAck(socket, event, ...args) {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
            reject(new Error(`${event} timed out`));
        }, 15000);

        socket.emit(event, ...args, (response) => {
            clearTimeout(timer);
            resolve(response);
        });
    });
}

function requireOk(name, response) {
    if (response && response.ok) {
        return response;
    }

    const detail = response && response.msg ? response.msg : "unknown error";
    throw new Error(`${name} failed: ${detail}`);
}

function defaultMonitor() {
    return {
        active: 1,
        accepted_statuscodes: ["200-299"],
        authDomain: null,
        authMethod: null,
        authWorkstation: null,
        basic_auth_pass: null,
        basic_auth_user: null,
        body: null,
        cacheBust: false,
        conditions: [],
        databaseConnectionString: null,
        databaseQuery: null,
        description: "",
        dns_resolve_server: "1.1.1.1",
        dns_resolve_type: "A",
        docker_container: "",
        docker_host: null,
        domainExpiryNotification: false,
        expiryNotification: false,
        expectedTlsAlert: null,
        expectedValue: null,
        game: null,
        gamedigGivenPortOnly: false,
        grpcBody: null,
        grpcEnableTls: false,
        grpcMetadata: null,
        grpcMethod: null,
        grpcProtobuf: null,
        grpcServiceName: null,
        grpcUrl: null,
        headers: null,
        hostname: "",
        httpBodyEncoding: "json",
        id: undefined,
        ignoreTls: false,
        interval: 60,
        invertKeyword: false,
        ipFamily: null,
        jsonPath: null,
        jsonPathOperator: null,
        kafkaProducerAllowAutoTopicCreation: false,
        kafkaProducerBrokers: [],
        kafkaProducerMessage: null,
        kafkaProducerSaslOptions: {},
        kafkaProducerSsl: false,
        kafkaProducerTopic: null,
        keyword: "",
        location: "",
        maxredirects: 10,
        maxretries: 0,
        method: "GET",
        mqttCheckType: null,
        mqttPassword: "",
        mqttSuccessMessage: "",
        mqttTopic: "",
        mqttUsername: "",
        mqttWebsocketPath: null,
        name: "",
        notificationIDList: {},
        oauth_audience: null,
        oauth_auth_method: null,
        oauth_client_id: null,
        oauth_client_secret: null,
        oauth_scopes: null,
        oauth_token_url: null,
        packetSize: null,
        ping_count: null,
        ping_numeric: false,
        ping_per_request_timeout: null,
        port: null,
        protocol: "",
        proxyId: null,
        pushToken: null,
        rabbitmqNodes: [],
        rabbitmqPassword: null,
        rabbitmqUsername: null,
        radiusCalledStationId: null,
        radiusCallingStationId: null,
        radiusPassword: null,
        radiusSecret: null,
        radiusUsername: null,
        remote_browser: null,
        resendInterval: 0,
        responseMaxLength: null,
        retryInterval: 60,
        retryOnlyOnStatusCodeFailure: false,
        saveErrorResponse: false,
        saveResponse: false,
        smtpSecurity: null,
        snmpOid: null,
        snmpVersion: null,
        subtype: null,
        system_service_name: null,
        tags: [],
        timeout: 48,
        tlsCa: null,
        tlsCert: null,
        tlsKey: null,
        type: "http",
        upsideDown: false,
        url: "http://127.0.0.1",
        wsIgnoreSecWebsocketAcceptHeader: false,
        wsSubprotocol: null,
        weight: 2000,
    };
}

function buildMonitorPayload(currentMonitor, monitorSpec, name) {
    const payload = currentMonitor ? { ...currentMonitor } : defaultMonitor();

    delete payload.cacheBust;
    delete payload.childrenIDs;
    delete payload.forceInactive;
    delete payload.includeSensitiveData;
    delete payload.maintenance;
    delete payload.parent;
    delete payload.path;
    delete payload.pathName;
    delete payload.screenshot;

    Object.assign(payload, monitorSpec, { name });

    payload.accepted_statuscodes = Array.isArray(payload.accepted_statuscodes)
        ? payload.accepted_statuscodes.map((value) => String(value))
        : ["200-299"];
    payload.conditions = Array.isArray(payload.conditions) ? payload.conditions : [];
    payload.kafkaProducerBrokers = Array.isArray(payload.kafkaProducerBrokers) ? payload.kafkaProducerBrokers : [];
    payload.kafkaProducerSaslOptions = payload.kafkaProducerSaslOptions && typeof payload.kafkaProducerSaslOptions === "object"
        ? payload.kafkaProducerSaslOptions
        : {};
    payload.notificationIDList = payload.notificationIDList && typeof payload.notificationIDList === "object"
        ? payload.notificationIDList
        : {};
    payload.rabbitmqNodes = Array.isArray(payload.rabbitmqNodes) ? payload.rabbitmqNodes : [];
    payload.tags = Array.isArray(payload.tags) ? payload.tags : [];

    return payload;
}

function indexMonitorsByName(monitorList) {
    const index = new Map();

    for (const [id, monitor] of Object.entries(monitorList || {})) {
        if (monitor && monitor.name) {
            index.set(monitor.name, {
                ...monitor,
                id: Number(monitor.id || id),
            });
        }
    }

    return index;
}

function indexStatusPagesBySlug(statusPageList) {
    const index = new Map();

    for (const page of Object.values(statusPageList || {})) {
        if (page && page.slug) {
            index.set(page.slug, page);
        }
    }

    return index;
}

function buildStatusPageConfig(currentConfig, desiredConfig) {
    return {
        analyticsId: desiredConfig.analyticsId ?? currentConfig.analyticsId ?? null,
        analyticsScriptUrl: desiredConfig.analyticsScriptUrl ?? currentConfig.analyticsScriptUrl ?? null,
        analyticsType: desiredConfig.analyticsType ?? currentConfig.analyticsType ?? null,
        autoRefreshInterval: desiredConfig.autoRefreshInterval ?? currentConfig.autoRefreshInterval ?? 300,
        customCSS: desiredConfig.customCSS ?? currentConfig.customCSS ?? "",
        description: desiredConfig.description ?? currentConfig.description ?? "",
        domainNameList: Array.isArray(desiredConfig.domainNameList)
            ? desiredConfig.domainNameList
            : (currentConfig.domainNameList || []),
        footerText: desiredConfig.footerText ?? currentConfig.footerText ?? "",
        logo: currentConfig.icon ?? "",
        rssTitle: desiredConfig.rssTitle ?? currentConfig.rssTitle ?? "",
        showCertificateExpiry: desiredConfig.showCertificateExpiry ?? currentConfig.showCertificateExpiry ?? false,
        showOnlyLastHeartbeat: desiredConfig.showOnlyLastHeartbeat ?? currentConfig.showOnlyLastHeartbeat ?? false,
        showPoweredBy: desiredConfig.showPoweredBy ?? currentConfig.showPoweredBy ?? false,
        showTags: desiredConfig.showTags ?? currentConfig.showTags ?? false,
        slug: desiredConfig.slug,
        theme: desiredConfig.theme ?? currentConfig.theme ?? "auto",
        title: desiredConfig.title,
    };
}

async function fetchStatusPage(baseUrl, slug) {
    const response = await fetch(`${baseUrl}/api/status-page/${encodeURIComponent(slug)}`);
    if (!response.ok) {
        return null;
    }
    return response.json();
}

function mergeManagedGroup(publicGroupList, groupName, monitorIDs) {
    const groups = Array.isArray(publicGroupList)
        ? publicGroupList.map((group) => ({
            id: group.id,
            name: group.name,
            monitorList: Array.isArray(group.monitorList)
                ? group.monitorList.map((monitor) => ({
                    id: monitor.id,
                    sendUrl: monitor.sendUrl,
                    url: monitor.url,
                }))
                : [],
        }))
        : [];

    const managedGroup = {
        name: groupName,
        monitorList: monitorIDs.map((id) => ({ id })),
    };

    const existingIndex = groups.findIndex((group) => group.name === groupName);
    if (existingIndex >= 0) {
        groups[existingIndex] = {
            ...groups[existingIndex],
            monitorList: managedGroup.monitorList,
        };
    } else {
        groups.push(managedGroup);
    }

    return groups;
}

async function main() {
    const password = readRequiredFile(passwordPath);
    const username = readOptionalFile(usernamePath, "admin");
    const desiredState = JSON.parse(fs.readFileSync(configPath, "utf8"));
    const socket = await connectSocket(baseUrl);

    try {
        const needsSetup = await emitAck(socket, "needSetup");
        if (needsSetup) {
            requireOk("setup", await emitAck(socket, "setup", username, password));
        }

        const monitorListPromise = waitForEvent(socket, "monitorList", 15000);
        const statusPageListPromise = waitForEvent(socket, "statusPageList", 15000);

        requireOk("login", await emitAck(socket, "login", {
            password,
            username,
        }));

        const monitorList = await monitorListPromise;
        const statusPageList = await statusPageListPromise;
        const monitorIndex = indexMonitorsByName(monitorList);
        const statusPageIndex = indexStatusPagesBySlug(statusPageList);
        const managedMonitorIDs = [];

        for (const monitorSpec of desiredState.monitors || []) {
            const existing = monitorIndex.get(monitorSpec.name);

            if (existing) {
                const currentMonitorResponse = requireOk("getMonitor", await emitAck(socket, "getMonitor", existing.id));
                const payload = buildMonitorPayload(currentMonitorResponse.monitor, monitorSpec.monitor, monitorSpec.name);
                payload.id = existing.id;
                requireOk("editMonitor", await emitAck(socket, "editMonitor", payload));
                managedMonitorIDs.push(existing.id);
            } else {
                const payload = buildMonitorPayload(null, monitorSpec.monitor, monitorSpec.name);
                delete payload.id;
                const response = requireOk("add", await emitAck(socket, "add", payload));
                managedMonitorIDs.push(Number(response.monitorID));
            }
        }

        const pageSpec = desiredState.statusPage;
        if (!statusPageIndex.has(pageSpec.slug)) {
            requireOk("addStatusPage", await emitAck(socket, "addStatusPage", pageSpec.title, pageSpec.slug));
        }

        const statusPageResponse = requireOk("getStatusPage", await emitAck(socket, "getStatusPage", pageSpec.slug));
        const currentPublicPage = await fetchStatusPage(baseUrl, pageSpec.slug);
        const publicGroupList = mergeManagedGroup(
            currentPublicPage ? currentPublicPage.publicGroupList : [],
            pageSpec.groupName,
            managedMonitorIDs,
        );
        const statusPageConfig = buildStatusPageConfig(statusPageResponse.config, pageSpec);

        requireOk(
            "saveStatusPage",
            await emitAck(socket, "saveStatusPage", pageSpec.slug, statusPageConfig, statusPageConfig.logo, publicGroupList),
        );

        console.log(`Provisioned ${managedMonitorIDs.length} Uptime Kuma monitors for ${username}`);
    } finally {
        socket.close();
    }
}

main().catch((error) => {
    console.error(error.message);
    process.exit(1);
});
