# YZD-S18 USB boot: no persistent environment or firmware writes.
setenv kernel_addr_r 0x11000000
setenv ramdisk_addr_r 0x15000000
setenv fdt_addr_r 0x08000000
setenv loadaddr 0x10400000
setenv initrd_high 0x7f800000
setenv fdt_high 0x20000000
if usb start; then
    for dev in 0 1 2 3 4 5 6 7; do
        setenv filesize
        setenv YZD_BOARD
        setenv LINUX
        setenv INITRD
        setenv FDT
        setenv APPEND
        if fatload usb ${dev}:1 ${loadaddr} /uEnv.txt; then
            if env import -t ${loadaddr} ${filesize}; then
                if test "${YZD_BOARD}" = "yzd-s18"; then
                    setenv bootargs "${APPEND}"
                    if printenv mac; then
                        setenv bootargs "${bootargs} mac=${mac}"
                    elif printenv eth_mac; then
                        setenv bootargs "${bootargs} mac=${eth_mac}"
                    elif printenv ethaddr; then
                        setenv bootargs "${bootargs} mac=${ethaddr}"
                    fi
                    if fatload usb ${dev}:1 ${kernel_addr_r} ${LINUX}; then
                        if fatload usb ${dev}:1 ${ramdisk_addr_r} ${INITRD}; then
                            if fatload usb ${dev}:1 ${fdt_addr_r} ${FDT}; then
                                if fdt addr ${fdt_addr_r}; then
                                    if fdt resize 65536; then
                                        booti ${kernel_addr_r} ${ramdisk_addr_r} ${fdt_addr_r}
                                    fi
                                fi
                            fi
                        fi
                    fi
                fi
            fi
        fi
    done
fi
