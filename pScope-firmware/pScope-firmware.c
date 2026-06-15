// pScope-firmware.c

#include <stdio.h>
#include "pico/stdlib.h"

#include <hardware/gpio.h>
#include "hardware/adc.h"
#include "hardware/dma.h"
#include "pico/multicore.h"

#define ADC_PIN        26
#define ADC_CHANNEL    0

#define N_SAMPLES      1024*16

static uint16_t samples[N_SAMPLES];


void core1_main();

int main()
{
    stdio_init_all();
    multicore_launch_core1(core1_main);


    sleep_ms(2000);

    printf("RP2040 ADC DMA Test\n");

    adc_init();
    adc_gpio_init(ADC_PIN);
    adc_select_input(ADC_CHANNEL);
    adc_fifo_setup(
        true,   // enable FIFO
        true,   // enable DMA request
        1,      // DREQ when at least 1 sample
        false,  // no ERR bit
        true    // shift to 12-bit
    );


    int dma_chan = dma_claim_unused_channel(true);
    // dma configs
    dma_channel_config cfg = dma_channel_get_default_config(dma_chan);
    channel_config_set_transfer_data_size(&cfg, DMA_SIZE_16);
    channel_config_set_read_increment(&cfg, false);
    channel_config_set_write_increment(&cfg, true);
    channel_config_set_dreq(&cfg, DREQ_ADC);


    while (true)
    {
        adc_fifo_drain();

        dma_channel_configure(
            dma_chan,
            &cfg,
            samples,
            &adc_hw->fifo,
            N_SAMPLES,
            false
        );

        dma_start_channel_mask(1u << dma_chan);

        adc_run(true);

        for (int i = 0; i < N_SAMPLES; i++){
            adc_hw->cs |= ADC_CS_START_ONCE_BITS;}
        
        dma_channel_wait_for_finish_blocking(dma_chan);

        adc_run(false);

        fwrite(samples, sizeof(samples), 1, stdout);
        fflush(stdout);

        printf("\n\n");

        sleep_ms(10);
    }

    return 0;
}



int led_pin = 2;  

void core1_main() {

    gpio_init(led_pin);
    gpio_set_dir(led_pin, GPIO_OUT);
    
    while (true) {
        gpio_xor_mask(1 << led_pin);
        sleep_ms(1);
    }

} 