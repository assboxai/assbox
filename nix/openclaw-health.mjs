// SPDX-License-Identifier: GPL-3.0-or-later
import { pathToFileURL } from "node:url";

const [rpcModulePath, ...args] = process.argv.slice(2);

function readOption(name) {
  const equalsPrefix = `${name}=`;
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === name) {
      return args[index + 1];
    }
    if (argument.startsWith(equalsPrefix)) {
      return argument.slice(equalsPrefix.length);
    }
  }
  return undefined;
}

if (args[0] !== "gateway" || args[1] !== "health") {
  throw new Error("the Assbox OpenClaw health client only handles gateway health");
}

const url = readOption("--url");
if (url !== "ws://127.0.0.1:18789") {
  throw new Error("the Assbox OpenClaw health client only handles the appliance loopback gateway");
}

const token = readOption("--token");
const password = readOption("--password");
if (token === undefined && password === undefined) {
  throw new Error("the appliance loopback health check requires explicit gateway credentials");
}

const timeout = readOption("--timeout") ?? "10000";
const json = args.includes("--json");
const { callGatewayFromCliRuntime } = await import(pathToFileURL(rpcModulePath).href);

try {
  const result = await callGatewayFromCliRuntime(
    "health",
    {
      url,
      token,
      password,
      timeout,
      json: true,
    },
    undefined,
    {
      defaultTimeoutMs: 10000,
      sharedStateMode: "read-only",
    },
  );

  if (!result || result.ok !== true) {
    throw new Error("the gateway returned an unhealthy response");
  }

  if (json) {
    console.log(JSON.stringify(result, null, 2));
  } else {
    console.log("Gateway Health");
    console.log("OK");
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
