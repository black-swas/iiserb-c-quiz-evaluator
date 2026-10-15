#include <stdio.h>

int main() {
    unsigned int val_input;
    int my_total_bits = 0;
    if (scanf("%u", &val_input) != 1) return 0;
    unsigned int temp_store = val_input;
    while (temp_store > 0) {
        if (temp_store % 2 == 1) {
            my_total_bits = my_total_bits + 1;
        }
        temp_store = temp_store / 2;
    }
    printf("%d\n", my_total_bits);
    return 0;
}
