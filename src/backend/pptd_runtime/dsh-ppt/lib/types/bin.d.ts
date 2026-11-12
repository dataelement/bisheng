#!/usr/bin/env node
/** Local, bounded command line interface for the local PPTD v2 toolchain. */
export interface CliIo {
    readonly stdout: {
        write(value: string): unknown;
    };
    readonly stderr: {
        write(value: string): unknown;
    };
}
/** Execute the CLI without terminating the host process. */
export declare function runCli(argv: readonly string[], io?: CliIo): Promise<number>;