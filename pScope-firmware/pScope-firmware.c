#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/adc.h"
#include "hardware/dma.h"
#include "pico/multicore.h"

#define ADC_PIN     26
#define ADC_CHANNEL 0

#define N_SAMPLES   1024

// --- Oversampling ----------------------------------------------------
// Each output sample is the average of OVERSAMPLE raw ADC readings.
// Averaging N uncorrelated samples reduces random noise by ~sqrt(N)
// (4x oversample -> ~2x lower noise, ~1 extra effective bit).
//
// The ADC core tops out around 500 ksps, so for OVERSAMPLE=4 the raw
// capture runs at ~400 ksps while the output frame still represents
// N_SAMPLES points spanning the same total capture time (~10.24 ms)
// as before -> frame size, timing, and protocol are unchanged.
#define OVERSAMPLE   1
#define RAW_SAMPLES (N_SAMPLES * OVERSAMPLE)

#define SYNC_WORD   0xA55A

static uint16_t raw_samples[RAW_SAMPLES];
static uint16_t samples[N_SAMPLES];

static int dma_chan;

static const uint led_pin = 2;

void core1_main()
{
    gpio_init(led_pin);
    gpio_set_dir(led_pin, GPIO_OUT);

    while (true)
    {
        gpio_xor_mask(1u << led_pin);
        sleep_ms(4);
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

    // Raw ADC clkdiv scaled so the *output* sample rate stays ~100 kS/s
    // even though OVERSAMPLE raw conversions feed each output sample.
    // Base: 479.0f -> 100 kS/s raw. Scaled: raw rate becomes
    // ~100 kS/s * OVERSAMPLE (must stay under the ADC's ~500 ksps limit).
    adc_set_clkdiv(479.0f / OVERSAMPLE);

    adc_fifo_setup(
        true,   // enable FIFO
        true,   // enable DMA requests
        1,      // DREQ asserted when FIFO has >= 1 sample
        false,  // no ERR bit
        false   // full 12-bit, no shift
    );

    adc_run(true); // free running mode

    // ---------------- DMA INIT ----------------
    dma_chan = dma_claim_unused_channel(true);
    if (dma_chan < 0) {
        printf("ERROR: no free DMA channel\n");
        while (true) {
            tight_loop_contents();
        }
    }

    dma_channel_config cfg = dma_channel_get_default_config(dma_chan);
    channel_config_set_transfer_data_size(&cfg, DMA_SIZE_16);
    channel_config_set_read_increment(&cfg, false);
    channel_config_set_write_increment(&cfg, true);
    channel_config_set_dreq(&cfg, DREQ_ADC);

    const uint16_t sync = SYNC_WORD;

    // ---------------- MAIN LOOP ----------------
    while (true)
    {
        // Drain any stale samples so this capture starts fresh
        adc_fifo_drain();

        dma_channel_configure(
            dma_chan,
            &cfg,
            raw_samples,    // write address
            &adc_hw->fifo,  // read address
            RAW_SAMPLES,
            true            // start immediately
        );

        dma_channel_wait_for_finish_blocking(dma_chan);

        // ---- Decimate: average each block of OVERSAMPLE raw samples ----
        for (int i = 0; i < N_SAMPLES; i++) {
            uint32_t acc = 0;
            for (int j = 0; j < OVERSAMPLE; j++) {
                acc += raw_samples[i * OVERSAMPLE + j];
            }
            samples[i] = (uint16_t)(acc / OVERSAMPLE);
        }

        // SEND FRAME: 2-byte sync word followed by N_SAMPLES uint16 values
        fwrite(&sync, sizeof(sync), 1, stdout);
        fwrite(samples, sizeof(samples), 1, stdout);
        fflush(stdout);
    }
}