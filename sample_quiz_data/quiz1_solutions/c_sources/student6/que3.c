#include <stdio.h>

int main() {
    long long n, acc = 0;
    if (scanf("%lld", &n) == 1) {
        for (long long i = 1; i < n; i++)
            acc += (i % 3 == 0 || i % 5 == 0) ? i : 0;
        printf("%lld\n", acc);
    }
    return 0;
}
