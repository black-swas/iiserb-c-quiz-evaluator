#include <stdio.h>

int main() {
    long long number;
    if (scanf("%lld", &number) != 1) return 0;
    int count_steps = 0;
    while (number > 1) {
        if (number % 2 == 0) {
            number = number / 2;
        } else {
            number = (3 * number) + 1;
        }
        count_steps++;
    }
    printf("%d\n", count_steps);
    return 0;
}
