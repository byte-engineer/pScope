#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/adc.h"
#include "hardware/dma.h"
#include "pico/multicore.h"

#define ADC_PIN     26
#define ADC_CHANNEL 0

#define N_SAMPLES   1024

static uint16_t samples[N_SAMPLES];

int dma_chan;
dma_channel_config cfg;

int led_pin = 2;

void core1_main()
{
    gpio_init(led_pin);
    gpio_set_dir(led_pin, GPIO_OUT);

    while (true)
    {
        gpio_xor_mask(1 << led_pin);
        sleep_ms(10);
    }
}

int main()
{
    stdio_init_all();
    multicore_launch_core1(core1_main);

    sleep_ms(2000);

    printf("RP2040 Scope Starting...\n");

    // ---------------- ADC INIT ----------------
    adc_init();
    adc_gpio_init(ADC_PIN);
    adc_select_input(ADC_CHANNEL);

    // Lock sample rate (100kS/s approx)
    adc_set_clkdiv(479.0f);

    adc_fifo_setup(
        true,   // enable FIFO
        true,   // enable DMA
        1,      // DREQ level
        false,  // no ERR bit
        false   // IMPORTANT: full 12-bit, no shift
    );

    adc_run(true); // FREE RUN MODE (IMPORTANT)

    // ---------------- DMA INIT ----------------
    dma_chan = dma_claim_unused_channel(true);

    cfg = dma_channel_get_default_config(dma_chan);

    channel_config_set_transfer_data_size(&cfg, DMA_SIZE_16);
    channel_config_set_read_increment(&cfg, false);
    channel_config_set_write_increment(&cfg, true);
    channel_config_set_dreq(&cfg, DREQ_ADC);

    uint16_t sync = 0xA55A;

    // ---------------- MAIN LOOP ----------------
    while (true)
    {
        adc_fifo_drain();

        dma_channel_configure(
            dma_chan,
            &cfg,
            samples,
            &adc_hw->fifo,
            N_SAMPLES,
            true
        );

        dma_channel_wait_for_finish_blocking(dma_chan);

        uint16_t sync = 0xA55A;
        fwrite(&sync, 2, 1, stdout);
        fwrite(samples, sizeof(samples), 1, stdout);

        // SEND FRAME
        fwrite(&sync, sizeof(sync), 1, stdout);
        fwrite(samples, sizeof(samples), 1, stdout);
        fflush(stdout);
    }
}